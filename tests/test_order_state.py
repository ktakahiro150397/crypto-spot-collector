import asyncio
from pathlib import Path
from typing import Any, Sequence

import pytest

from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderIntent,
    OrderStatus,
    SQLiteOrderIntentStore,
    create_intent,
)


class FakeAdapter:
    def __init__(self) -> None:
        self.submit_count = 0
        self.response: dict[str, Any] | Exception = {
            "id": "42",
            "status": "closed",
            "filled": 1.0,
        }
        self.order: dict[str, Any] | None = None
        self.open_orders: Sequence[dict[str, Any]] = []
        self.fills: Sequence[dict[str, Any]] = []
        self.positions: Sequence[dict[str, Any]] = []

    async def submit_market_order(self, intent: OrderIntent) -> dict[str, Any]:
        self.submit_count += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def fetch_order_by_cloid(self, symbol: str, cloid: str) -> dict[str, Any] | None:
        return self.order

    async def fetch_open_orders(self, symbol: str) -> Sequence[dict[str, Any]]:
        return self.open_orders

    async def fetch_fills(self, symbol: str) -> Sequence[dict[str, Any]]:
        return self.fills

    async def fetch_positions(self) -> Sequence[dict[str, Any]]:
        return self.positions


def intent() -> OrderIntent:
    return create_intent(
        strategy="sar-v1",
        symbol="BTC/USDC:USDC",
        timeframe="30m",
        candle_open_ms=123,
        side="buy",
        amount=1.0,
    )


def test_intent_id_and_cloid_are_deterministic_128_bit_hex() -> None:
    first = intent()
    second = intent()
    assert first.intent_id == second.intent_id
    assert first.cloid == second.cloid
    assert first.cloid.startswith("0x")
    assert len(first.cloid) == 34


@pytest.mark.asyncio
async def test_duplicate_execution_submits_only_once(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    executor = IdempotentOrderExecutor(adapter, SQLiteOrderIntentStore(tmp_path / "orders.sqlite"))
    first, second = await asyncio.gather(executor.execute(intent()), executor.execute(intent()))
    assert first.status is OrderStatus.FILLED
    assert second.status is OrderStatus.FILLED
    assert adapter.submit_count == 1


@pytest.mark.asyncio
async def test_timeout_reconciles_by_cloid_without_resubmit(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.response = TimeoutError()
    adapter.order = {
        "id": "77",
        "clientOrderId": intent().cloid,
        "status": "open",
        "filled": 0,
    }
    executor = IdempotentOrderExecutor(adapter, SQLiteOrderIntentStore(tmp_path / "orders.sqlite"))
    result = await executor.execute(intent())
    assert result.status is OrderStatus.OPEN
    assert result.order_id == "77"
    assert adapter.submit_count == 1

    again = await executor.execute(intent())
    assert again.status is OrderStatus.OPEN
    assert adapter.submit_count == 1


@pytest.mark.asyncio
async def test_ambiguous_timeout_stays_unknown(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.response = TimeoutError()
    adapter.positions = [{"symbol": "BTC/USDC:USDC", "contracts": 1}]
    executor = IdempotentOrderExecutor(adapter, SQLiteOrderIntentStore(tmp_path / "orders.sqlite"))
    result = await executor.execute(intent())
    assert result.status is OrderStatus.UNKNOWN
    assert "resubmit inhibited" in (result.error or "")
    await executor.execute(intent())
    assert adapter.submit_count == 1


@pytest.mark.asyncio
async def test_partial_fill_is_persisted(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.response = {"id": "1", "status": "open", "filled": 0.4}
    executor = IdempotentOrderExecutor(adapter, SQLiteOrderIntentStore(tmp_path / "orders.sqlite"))
    result = await executor.execute(intent())
    assert result.status is OrderStatus.PARTIALLY_FILLED
    assert result.filled == 0.4


def test_invalid_transition_is_rejected(tmp_path: Path) -> None:
    store = SQLiteOrderIntentStore(tmp_path / "orders.sqlite")
    created, _ = store.prepare(intent())
    with pytest.raises(ValueError, match="invalid order transition"):
        store.transition(created.intent_id, OrderStatus.FILLED)
