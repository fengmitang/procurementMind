from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.enums import PurchaseStatus, RoleCode
from app.domain.identity import CurrentUser, UserRole
from app.domain.workflow import (
    TRANSITION_RULES,
    TransitionRule,
    WorkflowCommand,
    WorkflowResult,
)
from app.models.procurement import PurchaseOperationLog, PurchaseRequest
from app.repositories.workflow import WorkflowRepository


class WorkflowService:
    def __init__(self, repository: WorkflowRepository | None = None) -> None:
        self.repository = repository or WorkflowRepository()

    async def transition(
        self,
        session: AsyncSession,
        current_user: CurrentUser,
        command: WorkflowCommand,
    ) -> WorkflowResult:
        if await self.repository.action_token_exists(session, command.action_token):
            raise AppError("DUPLICATE_OPERATION", "该操作已经执行", 409)

        purchase_request = await self.repository.get_request(session, command.request_id)
        if purchase_request is None:
            raise AppError("REQUIREMENT_NOT_FOUND", "采购申请不存在", 404)

        rule = TRANSITION_RULES[command.operation]
        actor_role = self._validate_actor(current_user, purchase_request, rule)
        self._validate_state_and_version(purchase_request, command, rule)
        next_handler = await self._resolve_next_handler(
            session,
            purchase_request,
            command,
            rule,
        )
        now = datetime.now()
        updated = await self.repository.advance_request(
            session,
            request_id=purchase_request.request_id,
            expected_version=command.expected_version,
            from_status=rule.from_status.value,
            to_status=rule.to_status.value,
            current_handler_employee_id=next_handler,
            submitted_at=(
                now if command.operation.value in {"SUBMIT_REVIEW", "RESUBMIT_REVIEW"} else None
            ),
            completed_at=now if rule.to_status == PurchaseStatus.COMPLETED else None,
        )
        if not updated:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请已被其他操作更新", 409)

        self.repository.add_operation_log(
            session,
            PurchaseOperationLog(
                request_id=purchase_request.request_id,
                operator_employee_id=current_user.employee_id,
                operator_platform_type_snapshot=current_user.platform_type,
                operator_platform_user_id_snapshot=current_user.platform_user_id,
                operator_name_snapshot=current_user.name,
                operator_mobile_snapshot=current_user.mobile,
                operator_role_id_snapshot=actor_role.role_id,
                operator_role_name_snapshot=actor_role.role_name,
                assigned_to_employee_id=next_handler,
                action_token=command.action_token,
                action_type=command.operation.value,
                from_status=rule.from_status.value,
                to_status=rule.to_status.value,
                operation_summary=command.operation_summary,
                operated_at=now,
            ),
        )
        try:
            await session.flush()
        except IntegrityError as exc:
            error_text = str(exc.orig).lower()
            if "action_token" in error_text:
                raise AppError("DUPLICATE_OPERATION", "该操作已经执行", 409) from exc
            raise

        return WorkflowResult(
            request_id=purchase_request.request_id,
            status=rule.to_status.value,
            version=command.expected_version + 1,
            current_handler_employee_id=next_handler,
        )

    @staticmethod
    def _validate_actor(
        current_user: CurrentUser,
        purchase_request: PurchaseRequest,
        rule: TransitionRule,
    ) -> UserRole:
        actor_role = next(
            (role for role in current_user.roles if role.role_code == rule.required_role.value),
            None,
        )
        if actor_role is None:
            raise AppError("PERMISSION_DENIED", "当前用户没有执行此操作的角色权限", 403)

        if rule.required_role == RoleCode.APPLICANT:
            if purchase_request.applicant_employee_id != current_user.employee_id:
                raise AppError("PERMISSION_DENIED", "只能操作本人发起的采购申请", 403)
        elif purchase_request.current_handler_employee_id != current_user.employee_id:
            raise AppError("PERMISSION_DENIED", "当前用户不是该采购申请的处理人", 403)

        if rule.required_role == RoleCode.BUILDING_MANAGER and not current_user.belongs_to_building(
            purchase_request.building_id
        ):
            raise AppError("BUILDING_NOT_ALLOWED", "当前楼长无权处理该楼宇申请", 403)
        return actor_role

    @staticmethod
    def _validate_state_and_version(
        purchase_request: PurchaseRequest,
        command: WorkflowCommand,
        rule: TransitionRule,
    ) -> None:
        if purchase_request.version != command.expected_version:
            raise AppError("CONCURRENT_MODIFICATION", "采购申请版本已变化", 409)
        if purchase_request.status != rule.from_status.value:
            raise AppError("INVALID_STATUS", "当前状态不允许执行该操作", 409)

    async def _resolve_next_handler(
        self,
        session: AsyncSession,
        purchase_request: PurchaseRequest,
        command: WorkflowCommand,
        rule: TransitionRule,
    ) -> int | None:
        if rule.clear_handler:
            return None
        if rule.assign_to_applicant:
            return purchase_request.applicant_employee_id
        if rule.target_role is None:
            return purchase_request.current_handler_employee_id
        if command.assigned_to_employee_id is None:
            raise AppError("INVALID_HANDLER", "必须指定下一处理人", 400)

        building_id = (
            purchase_request.building_id if rule.target_role == RoleCode.BUILDING_MANAGER else None
        )
        valid = await self.repository.is_valid_handler(
            session,
            command.assigned_to_employee_id,
            rule.target_role.value,
            building_id,
        )
        if not valid:
            raise AppError("INVALID_HANDLER", "指定人员不是合法处理人", 400)
        return command.assigned_to_employee_id
