from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversation"
    __table_args__ = (
        Index("ix_agent_conversation_employee_status", "employee_id", "status"),
        Index(
            "ix_agent_conversation_platform_conversation",
            "platform_type",
            "external_conversation_id",
        ),
        Index("ix_agent_conversation_purchase_request_id", "purchase_request_id"),
    )

    conversation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("employee.employee_id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    purchase_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("purchase_request.request_id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AgentMessage(Base):
    __tablename__ = "agent_message"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "external_message_id",
            name="uq_agent_message_conversation_external_message",
        ),
        Index("ix_agent_message_conversation_created", "conversation_id", "created_at"),
    )

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_conversation.conversation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_message_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class AgentSessionState(Base):
    __tablename__ = "agent_session_state"

    state_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_conversation.conversation_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    current_action: Mapped[str] = mapped_column(String(30), nullable=False)
    state_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    missing_fields: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    saved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
