import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

ResultT = TypeVar("ResultT")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    def __init__(self, retry_after_seconds: float) -> None:
        super().__init__("服务熔断中，请稍后重试")
        self.code = "CIRCUIT_OPEN"
        self.retry_after_seconds = max(0.0, retry_after_seconds)


@dataclass(frozen=True)
class CircuitSnapshot:
    state: CircuitState
    consecutive_failures: int
    failure_threshold: int
    recovery_timeout_seconds: float
    probe_in_flight: bool
    retry_after_seconds: float


@dataclass(frozen=True)
class _CallToken:
    state: CircuitState
    generation: int


class AsyncCircuitBreaker:
    """Concurrent circuit breaker with exactly one HALF_OPEN probe."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold 必须大于 0")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds 必须大于 0")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._generation = 0
        self._lock = asyncio.Lock()

    async def call(self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        token = await self._before_call()
        try:
            result = await operation()
        except asyncio.CancelledError:
            await self._cancel_call(token)
            raise
        except Exception:
            await self._record_failure(token)
            raise
        await self._record_success(token)
        return result

    async def snapshot(self) -> CircuitSnapshot:
        async with self._lock:
            return self._snapshot_unlocked()

    async def _before_call(self) -> _CallToken:
        async with self._lock:
            now = self.clock()
            if self._state is CircuitState.OPEN:
                retry_after = self._retry_after(now)
                if retry_after > 0:
                    raise CircuitOpenError(retry_after)
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                return _CallToken(CircuitState.HALF_OPEN, self._generation)
            if self._state is CircuitState.HALF_OPEN:
                raise CircuitOpenError(self.recovery_timeout_seconds)
            return _CallToken(CircuitState.CLOSED, self._generation)

    async def _record_success(self, token: _CallToken) -> None:
        async with self._lock:
            if token.state is CircuitState.HALF_OPEN:
                if self._state is CircuitState.HALF_OPEN and token.generation == self._generation:
                    self._close()
                return
            if self._state is CircuitState.CLOSED and token.generation == self._generation:
                self._consecutive_failures = 0

    async def _record_failure(self, token: _CallToken) -> None:
        async with self._lock:
            if token.state is CircuitState.HALF_OPEN:
                if self._state is CircuitState.HALF_OPEN and token.generation == self._generation:
                    self._open()
                return
            if self._state is not CircuitState.CLOSED or token.generation != self._generation:
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open()

    async def _cancel_call(self, token: _CallToken) -> None:
        async with self._lock:
            if (
                token.state is CircuitState.HALF_OPEN
                and self._state is CircuitState.HALF_OPEN
                and token.generation == self._generation
            ):
                self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self.clock()
        self._probe_in_flight = False
        self._generation += 1

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._probe_in_flight = False
        self._generation += 1

    def _retry_after(self, now: float) -> float:
        if self._opened_at is None:
            return self.recovery_timeout_seconds
        return max(0.0, self.recovery_timeout_seconds - (now - self._opened_at))

    def _snapshot_unlocked(self) -> CircuitSnapshot:
        return CircuitSnapshot(
            state=self._state,
            consecutive_failures=self._consecutive_failures,
            failure_threshold=self.failure_threshold,
            recovery_timeout_seconds=self.recovery_timeout_seconds,
            probe_in_flight=self._probe_in_flight,
            retry_after_seconds=(
                self._retry_after(self.clock()) if self._state is CircuitState.OPEN else 0.0
            ),
        )
