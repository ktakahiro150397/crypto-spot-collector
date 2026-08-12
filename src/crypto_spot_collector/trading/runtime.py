"""Signal-aware lifecycle for background tasks and async resources."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol


class AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class RuntimeSupervisor:
    def __init__(
        self,
        resources: Iterable[AsyncCloseable] = (),
        *,
        on_shutdown_requested: Callable[[], Any] | None = None,
    ) -> None:
        self.resources = list(resources)
        self.on_shutdown_requested = on_shutdown_requested
        self.shutdown_event = asyncio.Event()
        self.tasks: set[asyncio.Task[Any]] = set()
        self._closed = False

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_shutdown)
            except (NotImplementedError, RuntimeError):
                signal.signal(
                    sig,
                    lambda *_args, loop=loop: loop.call_soon_threadsafe(
                        self.request_shutdown
                    ),
                )

    def request_shutdown(self) -> None:
        if not self.shutdown_event.is_set():
            if self.on_shutdown_requested is not None:
                self.on_shutdown_requested()
            self.shutdown_event.set()

    async def run(self, coroutines: Iterable[Awaitable[Any]]) -> None:
        self.tasks = {asyncio.create_task(coro) for coro in coroutines}
        shutdown_waiter = asyncio.create_task(self.shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                self.tasks | {shutdown_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_waiter not in done:
                completed = next(iter(done))
                error = completed.exception()
                if error is not None:
                    raise error
                # A long-running worker returning unexpectedly is a fatal stop.
                raise RuntimeError("background worker exited unexpectedly")
        finally:
            shutdown_waiter.cancel()
            await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.on_shutdown_requested is not None:
            self.on_shutdown_requested()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for resource in reversed(self.resources):
            await resource.close()
