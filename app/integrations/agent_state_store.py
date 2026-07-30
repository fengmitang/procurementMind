import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import Settings, get_settings


class AgentStateStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def key(conversation_id: int) -> str:
        return f"agent:session:{conversation_id}"

    def _client(self) -> Redis:
        return Redis.from_url(self.settings.redis_url, decode_responses=True)

    async def get(self, conversation_id: int) -> dict[str, Any] | None:
        client = self._client()
        try:
            value = await client.get(self.key(conversation_id))
            if value is None:
                return None
            await client.expire(
                self.key(conversation_id),
                self.settings.agent_session_ttl_seconds,
            )
            return json.loads(value)
        finally:
            await client.aclose()

    async def set(self, conversation_id: int, state: dict[str, Any]) -> None:
        client = self._client()
        try:
            await client.set(
                self.key(conversation_id),
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                ex=self.settings.agent_session_ttl_seconds,
            )
        finally:
            await client.aclose()

    async def delete(self, conversation_id: int) -> bool:
        client = self._client()
        try:
            return bool(await client.delete(self.key(conversation_id)))
        finally:
            await client.aclose()
