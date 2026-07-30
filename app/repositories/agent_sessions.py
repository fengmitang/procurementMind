from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentConversation, AgentMessage, AgentSessionState
from app.models.identity import Employee


class AgentSessionRepository:
    async def lock_employee(self, session: AsyncSession, employee_id: int) -> None:
        await session.scalar(
            select(Employee).where(Employee.employee_id == employee_id).with_for_update()
        )

    async def get_active_by_action(
        self,
        session: AsyncSession,
        employee_id: int,
        current_action: str,
    ) -> AgentConversation | None:
        return await session.scalar(
            select(AgentConversation)
            .join(
                AgentSessionState,
                AgentSessionState.conversation_id == AgentConversation.conversation_id,
            )
            .where(
                AgentConversation.employee_id == employee_id,
                AgentConversation.status == "ACTIVE",
                AgentSessionState.current_action == current_action,
            )
            .order_by(AgentConversation.last_active_at.desc())
            .limit(1)
        )

    async def get_conversation(
        self,
        session: AsyncSession,
        conversation_id: int,
        *,
        for_update: bool = False,
    ) -> AgentConversation | None:
        statement = select(AgentConversation).where(
            AgentConversation.conversation_id == conversation_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_snapshot(
        self,
        session: AsyncSession,
        conversation_id: int,
    ) -> AgentSessionState | None:
        return await session.scalar(
            select(AgentSessionState).where(AgentSessionState.conversation_id == conversation_id)
        )

    async def get_message_by_external_id(
        self,
        session: AsyncSession,
        conversation_id: int,
        external_message_id: str,
    ) -> AgentMessage | None:
        return await session.scalar(
            select(AgentMessage).where(
                AgentMessage.conversation_id == conversation_id,
                AgentMessage.external_message_id == external_message_id,
            )
        )

    async def list_messages(
        self,
        session: AsyncSession,
        conversation_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[AgentMessage], int]:
        total = int(
            await session.scalar(
                select(func.count())
                .select_from(AgentMessage)
                .where(AgentMessage.conversation_id == conversation_id)
            )
            or 0
        )
        messages = list(
            (
                await session.scalars(
                    select(AgentMessage)
                    .where(AgentMessage.conversation_id == conversation_id)
                    .order_by(AgentMessage.created_at, AgentMessage.message_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return messages, total
