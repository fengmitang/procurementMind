from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import NotificationStatus


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_request_id", "request_id"),
        Index("ix_notification_outbox_event_type", "event_type"),
        Index("ix_notification_outbox_receiver_employee_id", "receiver_employee_id"),
        Index("ix_notification_outbox_status", "status"),
        Index("ix_notification_outbox_next_retry_at", "next_retry_at"),
    )

    notification_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    receiver_employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_type: Mapped[str] = mapped_column(String(30), nullable=False)
    receiver_platform_user_id_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=NotificationStatus.PENDING.value,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
