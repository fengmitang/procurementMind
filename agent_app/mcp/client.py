import asyncio
import os
import sys
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool

from agent_app.core.config import AgentSettings
from agent_app.mcp.runtime import PLATFORM_TYPE_ENV, PLATFORM_USER_ID_ENV, TRACE_ID_ENV
from agent_app.mcp.schemas import MCPToolResponse
from agent_app.schemas.backend import BackendIdentity


class MCPClientError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProcurementMCPClient:
    """Official stdio MCP client with a trusted per-process identity context."""

    def __init__(
        self,
        settings: AgentSettings,
        identity: BackendIdentity,
        trace_id: str,
        *,
        command: str | None = None,
        module: str | None = None,
    ) -> None:
        self.settings = settings
        self.identity = identity
        self.trace_id = trace_id
        self.command = command or sys.executable
        self.module = module or settings.mcp_server_module
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> Self:
        if self._stack is not None:
            raise MCPClientError("MCP_CLIENT_STATE_ERROR", "MCP Client 已连接")
        stack = AsyncExitStack()
        try:
            streams = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=self.command,
                        args=["-m", self.module],
                        env=self._server_environment(),
                    )
                )
            )
            session = await stack.enter_async_context(ClientSession(*streams))
            async with asyncio.timeout(self.settings.mcp_startup_timeout_seconds):
                await session.initialize()
        except TimeoutError as exc:
            try:
                await stack.aclose()
            except Exception:
                pass
            raise MCPClientError("MCP_STARTUP_TIMEOUT", "MCP 子进程启动或握手超时") from exc
        except Exception as exc:
            try:
                await stack.aclose()
            except Exception:
                pass
            raise MCPClientError("MCP_SUBPROCESS_ERROR", "MCP 子进程启动或握手失败") from exc
        self._stack = stack
        self._session = session
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            await stack.aclose()

    async def list_tools(self) -> list[Tool]:
        session = self._require_session()
        try:
            async with asyncio.timeout(self.settings.mcp_tool_timeout_seconds):
                result = await session.list_tools()
        except TimeoutError as exc:
            raise MCPClientError("MCP_TOOL_DISCOVERY_TIMEOUT", "MCP 工具发现超时") from exc
        except Exception as exc:
            raise MCPClientError("MCP_TRANSPORT_ERROR", "MCP 工具发现传输失败") from exc
        return result.tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> MCPToolResponse:
        session = self._require_session()
        try:
            async with asyncio.timeout(self.settings.mcp_tool_timeout_seconds):
                result = await session.call_tool(name, arguments or {})
        except TimeoutError as exc:
            raise MCPClientError("MCP_TOOL_TIMEOUT", f"MCP 工具 {name} 调用超时") from exc
        except Exception as exc:
            raise MCPClientError("MCP_TRANSPORT_ERROR", f"MCP 工具 {name} 传输失败") from exc
        return self._parse_result(name, result)

    def _server_environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment.update(
            {
                PLATFORM_TYPE_ENV: self.identity.platform_type,
                PLATFORM_USER_ID_ENV: self.identity.platform_user_id,
                TRACE_ID_ENV: self.trace_id,
                "PROCUREMENT_BACKEND_URL": self.settings.procurement_backend_url,
                "PROCUREMENT_BACKEND_TIMEOUT_SECONDS": str(
                    self.settings.procurement_backend_timeout_seconds
                ),
                "PROCUREMENT_BACKEND_MAX_RETRIES": str(
                    self.settings.procurement_backend_max_retries
                ),
                "PROCUREMENT_BACKEND_RETRY_DELAY_SECONDS": str(
                    self.settings.procurement_backend_retry_delay_seconds
                ),
                "IDENTITY_GATEWAY_SECRET": self.settings.identity_gateway_secret,
                "MCP_TOOL_TIMEOUT_SECONDS": str(self.settings.mcp_tool_timeout_seconds),
            }
        )
        return environment

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise MCPClientError("MCP_CLIENT_NOT_CONNECTED", "MCP Client 尚未连接")
        return self._session

    @staticmethod
    def _parse_result(name: str, result: CallToolResult) -> MCPToolResponse:
        if result.isError:
            messages = [getattr(item, "text", "") for item in result.content]
            detail = " ".join(message for message in messages if message).strip()
            raise MCPClientError("MCP_PROTOCOL_TOOL_ERROR", detail or f"MCP 工具 {name} 失败")
        if result.structuredContent is None:
            raise MCPClientError("MCP_INVALID_TOOL_RESULT", f"MCP 工具 {name} 未返回结构化结果")
        try:
            return MCPToolResponse.model_validate(result.structuredContent)
        except ValueError as exc:
            raise MCPClientError(
                "MCP_INVALID_TOOL_RESULT", f"MCP 工具 {name} 返回结构无效"
            ) from exc
