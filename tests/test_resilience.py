import asyncio

import pytest

from crypto_spot_collector.trading.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    ResilientCaller,
    RetryPolicy,
)


@pytest.mark.asyncio
async def test_read_retries_and_succeeds() -> None:
    caller = ResilientCaller(requests_per_second=10000)
    attempts = 0

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError()
        return "ok"

    result = await caller.call(
        "read",
        operation,
        policy=RetryPolicy(3, 1, 0, 0, 0),
    )
    assert result == "ok"
    assert attempts == 3
    assert caller.metrics["read"].retries == 2


@pytest.mark.asyncio
async def test_write_policy_does_not_blindly_retry() -> None:
    caller = ResilientCaller(requests_per_second=10000)
    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        await caller.call(
            "write", operation, policy=RetryPolicy(1, 1, 0, 0, 0)
        )
    assert attempts == 1


def test_circuit_opens_and_recovers() -> None:
    now = 0.0
    breaker = CircuitBreaker(2, 10, clock=lambda: now)
    breaker.failure()
    assert breaker.allow() is True
    breaker.failure()
    assert breaker.allow() is False
    now = 11.0
    assert breaker.allow() is True
    breaker.success()
    assert breaker.failures == 0
