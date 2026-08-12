from pathlib import Path
from typing import Any, Sequence

import pytest

from crypto_spot_collector.trading.protection import (
    ProtectionError,
    ProtectionReconciler,
    ProtectionSpec,
)


class FakeProtectionAdapter:
    def __init__(self) -> None:
        self.positions: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.created: list[ProtectionSpec] = []
        self.cancelled: list[str] = []
        self.fail_kind: str | None = None
        self.last_price = 100.0

    async def fetch_positions(self) -> Sequence[dict[str, Any]]:
        return self.positions

    async def fetch_open_orders(self, symbol: str) -> Sequence[dict[str, Any]]:
        return list(self.orders)

    async def fetch_fills(self, symbol: str) -> Sequence[dict[str, Any]]:
        return []

    async def fetch_last_price(self, symbol: str) -> float:
        return self.last_price

    async def create_protection_order(self, spec: ProtectionSpec) -> dict[str, Any]:
        if spec.kind == self.fail_kind:
            raise TimeoutError()
        self.created.append(spec)
        order = {
            "id": f"new-{spec.kind}",
            "amount": spec.amount,
            "triggerPrice": spec.trigger_price,
            "reduceOnly": True,
            "info": {
                "orderType": "Take Profit Market"
                if spec.kind == "take_profit"
                else "Stop Market"
            },
        }
        self.orders.append(order)
        return order

    async def cancel_protection_orders(
        self, symbol: str, order_ids: Sequence[str]
    ) -> None:
        self.cancelled.extend(order_ids)
        ids = set(order_ids)
        self.orders = [order for order in self.orders if str(order.get("id")) not in ids]


def reconciler(adapter: FakeProtectionAdapter) -> ProtectionReconciler:
    return ProtectionReconciler(
        adapter, take_profit_roe=3.0, stop_loss_roe=0.2, leverage=20
    )


def position(side: str = "long", contracts: float = 2.0) -> dict[str, Any]:
    return {
        "symbol": "BTC/USDC:USDC",
        "side": side,
        "contracts": contracts,
        "entryPrice": 100.0,
    }


@pytest.mark.asyncio
async def test_missing_pair_is_created_from_exchange_position() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position()]
    report = await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert {spec.kind for spec in adapter.created} == {"take_profit", "stop_loss"}
    assert all(spec.amount == 2.0 for spec in adapter.created)
    assert report.position is not None
    assert report.position.entry_price == 100.0


@pytest.mark.asyncio
async def test_old_orders_cancel_only_after_new_pair_verified() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position(contracts=2.0)]
    adapter.orders = [
        {
            "id": "old-tp",
            "amount": 1.0,
            "triggerPrice": 110,
            "reduceOnly": True,
            "info": {"orderType": "Take Profit Market"},
        },
        {
            "id": "old-sl",
            "amount": 1.0,
            "triggerPrice": 90,
            "reduceOnly": True,
            "info": {"orderType": "Stop Market"},
        },
    ]
    await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert set(adapter.cancelled) == {"old-tp", "old-sl"}
    assert len(adapter.orders) == 2


@pytest.mark.asyncio
async def test_create_failure_preserves_existing_orders() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position()]
    adapter.orders = [
        {
            "id": "old-sl",
            "amount": 1.0,
            "triggerPrice": 90,
            "reduceOnly": True,
            "info": {"orderType": "Stop Market"},
        }
    ]
    adapter.fail_kind = "take_profit"
    with pytest.raises(ProtectionError):
        await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert adapter.cancelled == []
    assert any(order["id"] == "old-sl" for order in adapter.orders)


@pytest.mark.asyncio
async def test_orphan_protection_is_cancelled_when_flat() -> None:
    adapter = FakeProtectionAdapter()
    adapter.orders = [
        {
            "id": "orphan",
            "amount": 1,
            "triggerPrice": 90,
            "reduceOnly": True,
            "info": {"orderType": "Stop Market"},
        }
    ]
    report = await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert report.orphan_count == 1
    assert adapter.cancelled == ["orphan"]


@pytest.mark.asyncio
async def test_recovered_trailing_stop_never_moves_backward() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position()]
    adapter.last_price = 106
    adapter.orders = [
        {
            "id": "trailing-sl",
            "amount": 2,
            "triggerPrice": 105,
            "reduceOnly": True,
            "info": {"orderType": "Stop Market"},
        }
    ]
    await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC", trailing_stop=103)
    stop = next(
        order
        for order in adapter.orders
        if order.get("info", {}).get("orderType") == "Stop Market"
    )
    assert stop["triggerPrice"] == 105


@pytest.mark.asyncio
async def test_actual_position_leverage_drives_protection_prices() -> None:
    adapter = FakeProtectionAdapter()
    actual = position()
    actual["leverage"] = 10
    adapter.positions = [actual]
    await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    take_profit = next(spec for spec in adapter.created if spec.kind == "take_profit")
    assert take_profit.trigger_price == 130


@pytest.mark.asyncio
async def test_exchange_price_rounding_is_accepted_during_verification() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position()]
    adapter.orders = [
        {
            "id": "rounded-tp",
            "amount": 2,
            "triggerPrice": 115.0004,
            "reduceOnly": True,
            "info": {"orderType": "Take Profit Market"},
        },
        {
            "id": "rounded-sl",
            "amount": 2,
            "triggerPrice": 99.0004,
            "reduceOnly": True,
            "info": {"orderType": "Stop Market"},
        },
    ]
    await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert adapter.created == []


@pytest.mark.asyncio
async def test_breached_stop_requires_reduce_only_close_without_new_orders() -> None:
    adapter = FakeProtectionAdapter()
    adapter.positions = [position()]
    adapter.last_price = 98.0
    with pytest.raises(ProtectionError, match="already breached"):
        await reconciler(adapter).reconcile_symbol("BTC/USDC:USDC")
    assert adapter.created == []
    assert adapter.cancelled == []
