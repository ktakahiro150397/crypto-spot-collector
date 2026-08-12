import asyncio

import pytest

from crypto_spot_collector.trading.runtime import RuntimeSupervisor


class Resource:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_shutdown_cancels_tasks_and_closes_resources() -> None:
    resource = Resource()
    stopped = False
    gate = asyncio.Event()

    async def worker() -> None:
        nonlocal stopped
        try:
            await gate.wait()
        finally:
            stopped = True

    supervisor = RuntimeSupervisor([resource])
    running = asyncio.create_task(supervisor.run([worker()]))
    await asyncio.sleep(0)
    supervisor.request_shutdown()
    await running
    assert stopped is True
    assert resource.closed is True


@pytest.mark.asyncio
async def test_worker_failure_closes_resources() -> None:
    resource = Resource()

    async def broken() -> None:
        raise ValueError("boom")

    supervisor = RuntimeSupervisor([resource])
    with pytest.raises(ValueError, match="boom"):
        await supervisor.run([broken()])
    assert resource.closed is True
