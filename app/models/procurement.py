from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import PurchaseStatus, ReviewStatus


class Supplier(Base):
    __tablename__ = "supplier"
    __table_args__ = (
        UniqueConstraint(
            "unified_social_credit_code",
            name="uq_supplier_unified_social_credit_code",
        ),
        Index("ix_supplier_supplier_name", "supplier_name"),
    )

    supplier_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registered_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contract_contact_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PurchaseRequest(Base):
    __tablename__ = "purchase_request"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("version >= 0", name="version_non_negative"),
        Index("ix_purchase_request_applicant_employee_id", "applicant_employee_id"),
        Index("ix_purchase_request_status", "status"),
        Index("ix_purchase_request_current_handler_employee_id", "current_handler_employee_id"),
        Index("ix_purchase_request_building_id", "building_id"),
        Index("ix_purchase_request_updated_at", "updated_at"),
    )

    request_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    building_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("building.building_id", ondelete="RESTRICT"),
        nullable=False,
    )
    applicant_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    applicant_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    applicant_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    applicant_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    applicant_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_profession: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    quantity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    application_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicant_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PurchaseStatus.DRAFT.value
    )
    current_handler_employee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PurchaseReview(Base):
    __tablename__ = "purchase_review"
    __table_args__ = (
        UniqueConstraint("request_id", "review_round", name="uq_purchase_review_round"),
        CheckConstraint("review_round > 0", name="review_round_positive"),
        CheckConstraint(
            "estimated_unit_price IS NULL OR estimated_unit_price >= 0",
            name="estimated_unit_price_non_negative",
        ),
        CheckConstraint(
            "estimated_total_price IS NULL OR estimated_total_price >= 0",
            name="estimated_total_price_non_negative",
        ),
        Index("ix_purchase_review_request_id", "request_id"),
        Index("ix_purchase_review_reviewer_employee_id", "reviewer_employee_id"),
        Index("ix_purchase_review_proposed_supplier_id", "proposed_supplier_id"),
    )

    review_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_round: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.DRAFT.value
    )
    reviewer_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewer_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    reviewer_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    reviewer_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_opinion: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_supplier_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("supplier.supplier_id", ondelete="RESTRICT"),
        nullable=True,
    )
    proposed_supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    supplier_contact_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estimated_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estimated_total_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    need_contract: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contract_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_arrival_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PurchaseExecution(Base):
    __tablename__ = "purchase_execution"
    __table_args__ = (
        CheckConstraint("actual_unit_price >= 0", name="actual_unit_price_non_negative"),
        CheckConstraint("actual_total_price >= 0", name="actual_total_price_non_negative"),
        CheckConstraint(
            "tax_rate IS NULL OR (tax_rate >= 0 AND tax_rate <= 100)",
            name="tax_rate_range",
        ),
        Index("ix_purchase_execution_purchaser_employee_id", "purchaser_employee_id"),
        Index("ix_purchase_execution_supplier_id", "supplier_id"),
    )

    execution_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    purchaser_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    purchaser_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    purchaser_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    purchaser_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    purchaser_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("supplier.supplier_id", ondelete="RESTRICT"),
        nullable=False,
    )
    supplier_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_tax_no_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supplier_bank_name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supplier_bank_account_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_address_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contract_contact_info_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actual_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_total_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    execution_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class WarehouseReceipt(Base):
    __tablename__ = "warehouse_receipt"
    __table_args__ = (
        CheckConstraint("received_quantity > 0", name="received_quantity_positive"),
        Index("ix_warehouse_receipt_warehouse_employee_id", "warehouse_employee_id"),
    )

    receipt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    warehouse_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    warehouse_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    warehouse_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    warehouse_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    warehouse_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warehouse_location: Mapped[str] = mapped_column(String(255), nullable=False)
    received_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SupplierBlacklist(Base):
    __tablename__ = "supplier_blacklist"
    __table_args__ = (
        CheckConstraint(
            "(duration_type = 'PERMANENT' AND end_at IS NULL) OR "
            "(duration_type = 'LIMITED' AND end_at IS NOT NULL)",
            name="duration_end_at_consistency",
        ),
        Index("ix_supplier_blacklist_supplier_id", "supplier_id"),
        Index("ix_supplier_blacklist_source_request_id", "source_request_id"),
        Index("ix_supplier_blacklist_registrar_employee_id", "registrar_employee_id"),
        Index("ix_supplier_blacklist_released_by_employee_id", "released_by_employee_id"),
        Index("ix_supplier_blacklist_status", "status"),
    )

    blacklist_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("supplier.supplier_id", ondelete="RESTRICT"),
        nullable=False,
    )
    supplier_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    source_request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    registrar_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    registrar_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    registrar_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    registrar_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    registrar_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blacklist_type: Mapped[str] = mapped_column(String(50), nullable=False)
    blacklist_reason: Mapped[str] = mapped_column(Text, nullable=False)
    duration_type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by_employee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=True,
    )
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class PurchaseOperationLog(Base):
    __tablename__ = "purchase_operation_log"
    __table_args__ = (
        Index("ix_purchase_operation_log_request_id", "request_id"),
        Index("ix_purchase_operation_log_operator_employee_id", "operator_employee_id"),
        Index("ix_purchase_operation_log_assigned_to_employee_id", "assigned_to_employee_id"),
        Index("ix_purchase_operation_log_action_type", "action_type"),
        Index("ix_purchase_operation_log_operated_at", "operated_at"),
    )

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator_platform_type_snapshot: Mapped[str] = mapped_column(String(30), nullable=False)
    operator_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    operator_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    operator_mobile_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_role_id_snapshot: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_role_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    assigned_to_employee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=True,
    )
    action_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    operated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
