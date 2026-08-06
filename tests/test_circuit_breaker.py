import asyncio

import pytest

from agent_app.resilience import AsyncCircuitBreaker, CircuitOpenError, CircuitState


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


async def fail() -> None:
    raise RuntimeError("dependency failed")


@pytest.mark.asyncio
async def test_circuit_opens_at_threshold_and_recovers_after_probe() -> None:
    clock = Clock()
    breaker = AsyncCircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=10,
        clock=clock,
    )

    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    opened = await breaker.snapshot()
    assert opened.state is CircuitState.OPEN
    assert opened.consecutive_failures == 2

    with pytest.raises(CircuitOpenError) as blocked:
        await breaker.call(lambda: asyncio.sleep(0))
    assert blocked.value.retry_after_seconds == pytest.approx(10)

    clock.value += 10
    assert await breaker.call(lambda: asyncio.sleep(0, result="recovered")) == "recovered"
    recovered = await breaker.snapshot()
    assert recovered.state is CircuitState.CLOSED
    assert recovered.consecutive_failures == 0


@pytest.mark.asyncio
async def test_half_open_allows_exactly_one_concurrent_probe() -> None:
    clock = Clock()
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=5,
        clock=clock,
    )
    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    clock.value += 5
    entered = asyncio.Event()
    release = asyncio.Event()

    async def probe() -> str:
        entered.set()
        await release.wait()
        return "ok"

    probe_task = asyncio.create_task(breaker.call(probe))
    await entered.wait()
    half_open = await breaker.snapshot()
    assert half_open.state is CircuitState.HALF_OPEN
    assert half_open.probe_in_flight is True

    with pytest.raises(CircuitOpenError):
        await breaker.call(lambda: asyncio.sleep(0))

    release.set()
    assert await probe_task == "ok"
    assert (await breaker.snapshot()).state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_failed_half_open_probe_reopens_full_recovery_window() -> None:
    clock = Clock()
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=7,
        clock=clock,
    )
    with pytest.raises(RuntimeError):
        await breaker.call(fail)
    clock.value += 7
    with pytest.raises(RuntimeError):
        await breaker.call(fail)

    reopened = await breaker.snapshot()
    assert reopened.state is CircuitState.OPEN
    assert reopened.retry_after_seconds == pytest.approx(7)


def test_circuit_configuration_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        AsyncCircuitBreaker(failure_threshold=0, recovery_timeout_seconds=1)
    with pytest.raises(ValueError, match="recovery_timeout_seconds"):
        AsyncCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0)
