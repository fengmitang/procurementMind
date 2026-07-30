import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.db.session import async_session_factory, engine
from app.domain.enums import PurchaseStatus
from app.domain.identity import CurrentUser, UserBuilding, UserRole
from app.domain.workflow import (
    TRANSITION_RULES,
    WorkflowCommand,
    WorkflowOperation,
)
from app.models.procurement import PurchaseOperationLog, PurchaseRequest
from app.repositories.workflow import WorkflowRepository
from app.services.workflow import WorkflowService
from scripts.seed_demo_data import seed_demo_data


def applicant_user() -> CurrentUser:
    return CurrentUser(
        employee_id=90001,
        employee_no="TEST-E001",
        name="测试需求人",
        mobile="13800009001",
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-01",
        roles=(UserRole(1, "APPLICANT", "需求人"),),
        buildings=(UserBuilding(1, "一号楼", True),),
    )


def purchaser_user() -> CurrentUser:
    return CurrentUser(
        employee_id=90003,
        employee_no="TEST-E003",
        name="测试采购员",
        mobile="13800009003",
        platform_type="TEST_PLATFORM",
        platform_user_id="test-user-03",
        roles=(UserRole(3, "PURCHASER", "采购员"),),
        buildings=(),
    )


@pytest.fixture(autouse=True)
async def reset_demo_workflow_data() -> None:
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()
    yield
    await engine.dispose()
    await seed_demo_data()
    await engine.dispose()


def test_transition_table_covers_the_complete_main_flow() -> None:
    transitions = {
        operation: (rule.from_status, rule.to_status)
        for operation, rule in TRANSITION_RULES.items()
    }
    assert transitions == {
        WorkflowOperation.SUBMIT_REVIEW: (
            PurchaseStatus.DRAFT,
            PurchaseStatus.PENDING_REVIEW,
        ),
        WorkflowOperation.REJECT: (
            PurchaseStatus.PENDING_REVIEW,
            PurchaseStatus.REJECTED,
        ),
        WorkflowOperation.RESUBMIT_REVIEW: (
            PurchaseStatus.REJECTED,
            PurchaseStatus.PENDING_REVIEW,
        ),
        WorkflowOperation.SUBMIT_PURCHASER: (
            PurchaseStatus.PENDING_REVIEW,
            PurchaseStatus.PENDING_PURCHASE,
        ),
        WorkflowOperation.START_PURCHASE: (
            PurchaseStatus.PENDING_PURCHASE,
            PurchaseStatus.PURCHASING,
        ),
        WorkflowOperation.SUBMIT_WAREHOUSE: (
            PurchaseStatus.PURCHASING,
            PurchaseStatus.PENDING_WAREHOUSE,
        ),
        WorkflowOperation.COMPLETE: (
            PurchaseStatus.PENDING_WAREHOUSE,
            PurchaseStatus.COMPLETED,
        ),
    }


@pytest.mark.asyncio
async def test_transition_updates_status_version_handler_and_log_atomically() -> None:
    command = WorkflowCommand(
        request_id=91001,
        operation=WorkflowOperation.SUBMIT_REVIEW,
        expected_version=0,
        action_token="TEST-WORKFLOW-SUBMIT-REVIEW",
        assigned_to_employee_id=90002,
        operation_summary="提交一号楼楼长审核",
    )
    async with async_session_factory() as session:
        async with session.begin():
            result = await WorkflowService().transition(
                session,
                applicant_user(),
                command,
            )

    assert result.status == "PENDING_REVIEW"
    assert result.version == 1
    assert result.current_handler_employee_id == 90002

    async with async_session_factory() as session:
        request = await session.get(PurchaseRequest, 91001)
        log = await session.scalar(
            select(PurchaseOperationLog).where(
                PurchaseOperationLog.action_token == command.action_token
            )
        )
    assert request is not None
    assert request.status == "PENDING_REVIEW"
    assert request.version == 1
    assert request.current_handler_employee_id == 90002
    assert log is not None
    assert log.from_status == "DRAFT"
    assert log.to_status == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_rejects_invalid_status_and_stale_version() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            with pytest.raises(AppError) as invalid_status:
                await WorkflowService().transition(
                    session,
                    purchaser_user(),
                    WorkflowCommand(
                        request_id=91005,
                        operation=WorkflowOperation.START_PURCHASE,
                        expected_version=4,
                        action_token="TEST-WORKFLOW-INVALID-STATUS",
                    ),
                )
    assert invalid_status.value.code == "INVALID_STATUS"

    async with async_session_factory() as session:
        async with session.begin():
            with pytest.raises(AppError) as stale_version:
                await WorkflowService().transition(
                    session,
                    applicant_user(),
                    WorkflowCommand(
                        request_id=91001,
                        operation=WorkflowOperation.SUBMIT_REVIEW,
                        expected_version=99,
                        action_token="TEST-WORKFLOW-STALE-VERSION",
                        assigned_to_employee_id=90002,
                    ),
                )
    assert stale_version.value.code == "CONCURRENT_MODIFICATION"


@pytest.mark.asyncio
async def test_rejects_duplicate_action_token() -> None:
    command = WorkflowCommand(
        request_id=91001,
        operation=WorkflowOperation.SUBMIT_REVIEW,
        expected_version=0,
        action_token="TEST-WORKFLOW-DUPLICATE",
        assigned_to_employee_id=90002,
    )
    async with async_session_factory() as session:
        async with session.begin():
            await WorkflowService().transition(session, applicant_user(), command)

    async with async_session_factory() as session:
        async with session.begin():
            with pytest.raises(AppError) as duplicate:
                await WorkflowService().transition(session, applicant_user(), command)
    assert duplicate.value.code == "DUPLICATE_OPERATION"


@pytest.mark.asyncio
async def test_rejects_handler_from_another_building() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            with pytest.raises(AppError) as invalid_handler:
                await WorkflowService().transition(
                    session,
                    applicant_user(),
                    WorkflowCommand(
                        request_id=91001,
                        operation=WorkflowOperation.SUBMIT_REVIEW,
                        expected_version=0,
                        action_token="TEST-WORKFLOW-CROSS-BUILDING",
                        assigned_to_employee_id=90007,
                    ),
                )
    assert invalid_handler.value.code == "INVALID_HANDLER"


class FailingLogRepository(WorkflowRepository):
    def add_operation_log(
        self,
        session,
        operation_log,
    ) -> None:
        raise RuntimeError("simulated operation log failure")


@pytest.mark.asyncio
async def test_request_update_rolls_back_when_operation_log_fails() -> None:
    with pytest.raises(RuntimeError, match="simulated operation log failure"):
        async with async_session_factory() as session:
            async with session.begin():
                await WorkflowService(FailingLogRepository()).transition(
                    session,
                    applicant_user(),
                    WorkflowCommand(
                        request_id=91001,
                        operation=WorkflowOperation.SUBMIT_REVIEW,
                        expected_version=0,
                        action_token="TEST-WORKFLOW-ROLLBACK",
                        assigned_to_employee_id=90002,
                    ),
                )

    async with async_session_factory() as session:
        request = await session.get(PurchaseRequest, 91001)
        log = await session.scalar(
            select(PurchaseOperationLog).where(
                PurchaseOperationLog.action_token == "TEST-WORKFLOW-ROLLBACK"
            )
        )
    assert request is not None
    assert request.status == "DRAFT"
    assert request.version == 0
    assert log is None
