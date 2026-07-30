from dataclasses import dataclass
from enum import StrEnum

from app.domain.enums import PurchaseStatus, RoleCode


class WorkflowOperation(StrEnum):
    SUBMIT_REVIEW = "SUBMIT_REVIEW"
    REJECT = "REJECT"
    RESUBMIT_REVIEW = "RESUBMIT_REVIEW"
    SUBMIT_PURCHASER = "SUBMIT_PURCHASER"
    START_PURCHASE = "START_PURCHASE"
    SUBMIT_WAREHOUSE = "SUBMIT_WAREHOUSE"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class TransitionRule:
    from_status: PurchaseStatus
    to_status: PurchaseStatus
    required_role: RoleCode
    target_role: RoleCode | None = None
    assign_to_applicant: bool = False
    clear_handler: bool = False


TRANSITION_RULES = {
    WorkflowOperation.SUBMIT_REVIEW: TransitionRule(
        PurchaseStatus.DRAFT,
        PurchaseStatus.PENDING_REVIEW,
        RoleCode.APPLICANT,
        target_role=RoleCode.BUILDING_MANAGER,
    ),
    WorkflowOperation.REJECT: TransitionRule(
        PurchaseStatus.PENDING_REVIEW,
        PurchaseStatus.REJECTED,
        RoleCode.BUILDING_MANAGER,
        assign_to_applicant=True,
    ),
    WorkflowOperation.RESUBMIT_REVIEW: TransitionRule(
        PurchaseStatus.REJECTED,
        PurchaseStatus.PENDING_REVIEW,
        RoleCode.APPLICANT,
        target_role=RoleCode.BUILDING_MANAGER,
    ),
    WorkflowOperation.SUBMIT_PURCHASER: TransitionRule(
        PurchaseStatus.PENDING_REVIEW,
        PurchaseStatus.PENDING_PURCHASE,
        RoleCode.BUILDING_MANAGER,
        target_role=RoleCode.PURCHASER,
    ),
    WorkflowOperation.START_PURCHASE: TransitionRule(
        PurchaseStatus.PENDING_PURCHASE,
        PurchaseStatus.PURCHASING,
        RoleCode.PURCHASER,
    ),
    WorkflowOperation.SUBMIT_WAREHOUSE: TransitionRule(
        PurchaseStatus.PURCHASING,
        PurchaseStatus.PENDING_WAREHOUSE,
        RoleCode.PURCHASER,
        target_role=RoleCode.WAREHOUSE_MANAGER,
    ),
    WorkflowOperation.COMPLETE: TransitionRule(
        PurchaseStatus.PENDING_WAREHOUSE,
        PurchaseStatus.COMPLETED,
        RoleCode.WAREHOUSE_MANAGER,
        clear_handler=True,
    ),
}


@dataclass(frozen=True, slots=True)
class WorkflowCommand:
    request_id: int
    operation: WorkflowOperation
    expected_version: int
    action_token: str
    assigned_to_employee_id: int | None = None
    operation_summary: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    request_id: int
    status: str
    version: int
    current_handler_employee_id: int | None
