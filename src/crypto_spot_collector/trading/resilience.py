"""Bounded REST retries, jittered backoff, rate limiting and circuit breaking."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int
    timeout_seconds: float
    initial_delay_seconds: float
    max_delay_seconds: float
    jitter_ratio: float = 0.2


READ_POLICY = RetryPolicy(4, 15.0, 0.5, 8.0)
# Blind writes must never be retried. OrderIntent reconciliation decides what
# happened after a timeout before any future action is permitted.
WRITE_POLICY = RetryPolicy(1, 15.0, 0.0, 0.0)
IDEMPOTENT_WRITE_POLICY = RetryPolicy(3, 15.0, 0.5, 4.0)


@dataclass
class ResilienceMetrics:
    calls: int = 0
    retries: int = 0
    failures: int = 0
    circuit_rejections: int = 0


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return self.clock() - self.opened_at >= self.recovery_seconds

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = self.clock()


class RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_at = max(now, self._next_at) + self.interval


class ResilientCaller:
    def __init__(self, requests_per_second: float = 10.0) -> None:
        self.rate_limiter = RateLimiter(requests_per_second)
        self.breakers: dict[str, CircuitBreaker] = {}
        self.metrics: dict[str, ResilienceMetrics] = {}

    async def call(
        self,
        operation: str,
        function: Callable[[], Awaitable[T]],
        *,
        policy: RetryPolicy = READ_POLICY,
    ) -> T:
        breaker = self.breakers.setdefault(operation, CircuitBreaker())
        metrics = self.metrics.setdefault(operation, ResilienceMetrics())
        metrics.calls += 1
        if not breaker.allow():
            metrics.circuit_rejections += 1
            raise CircuitOpenError(f"circuit is open for {operation}")

        delay = policy.initial_delay_seconds
        last_error: BaseException | None = None
        for attempt in range(policy.attempts):
            await self.rate_limiter.acquire()
            try:
                result = await asyncio.wait_for(
                    function(), timeout=policy.timeout_seconds
                )
            except (TimeoutError, asyncio.TimeoutError, ConnectionError) as exc:
                last_error = exc
                breaker.failure()
                if attempt + 1 >= policy.attempts:
                    break
                metrics.retries += 1
                jitter = delay * policy.jitter_ratio * random.random()
                await asyncio.sleep(min(policy.max_delay_seconds, delay + jitter))
                delay = min(policy.max_delay_seconds, max(delay * 2, 0.001))
            else:
                breaker.success()
                return result
        metrics.failures += 1
        assert last_error is not None
        raise last_error
