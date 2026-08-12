from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Employee(Base):
    __tablename__ = "employee"
    __table_args__ = (
        UniqueConstraint("employee_no", name="uq_employee_employee_no"),
        Index("ix_employee_name", "name"),
        Index("ix_employee_mobile", "mobile"),
    )

    employee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employee_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmployeeExternalIdentity(Base):
    __tablename__ = "employee_external_identity"
    __table_args__ = (
        UniqueConstraint(
            "platform_type",
            "platform_user_id",
            name="uq_employee_external_identity_platform_user",
        ),
        Index("ix_employee_external_identity_employee_id", "employee_id"),
    )

    identity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_type: Mapped[str] = mapped_column(String(30), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Building(Base):
    __tablename__ = "building"

    building_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    building_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EmployeeBuilding(Base):
    __tablename__ = "employee_building"
    __table_args__ = (Index("ix_employee_building_building_id", "building_id"),)

    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    building_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("building.building_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Role(Base):
    __tablename__ = "role"

    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EmployeeRole(Base):
    __tablename__ = "employee_role"
    __table_args__ = (Index("ix_employee_role_role_id", "role_id"),)

    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("role.role_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdminOperationLog(Base):
    __tablename__ = "admin_operation_log"
    __table_args__ = (
        UniqueConstraint("action_token", name="uq_admin_operation_log_action_token"),
        Index("ix_admin_operation_log_admin_employee_id", "admin_employee_id"),
        Index("ix_admin_operation_log_target_employee_id", "target_employee_id"),
    )

    operation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_employee_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
