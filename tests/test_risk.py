import math
from pathlib import Path
from typing import Any, Sequence

import pytest

from crypto_spot_collector.trading.config import TradingConfig
from crypto_spot_collector.trading.risk import EntryRiskError, EntryRiskGuard

BTC = "BTC/USDC:USDC"
ETH = "ETH/USDC:USDC"


def config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": (BTC, ETH),
        "timeframe": "30m",
        "amount_usdc": 10.0,
        "leverage": 5,
        "take_profit_roe": 3.0,
        "stop_loss_roe": 0.2,
        "trailing_interval_minutes": 3,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 4,
        "sar_close_consecutive_count": 2,
        "price_change_threshold_percent": 999.0,
        "max_order_notional_usdc": 20.0,
        "max_symbol_notional_usdc": 25.0,
        "max_total_notional_usdc": 50.0,
        "max_positions": 2,
        "max_leverage": 5,
        "min_free_collateral_usdc": 10.0,
    }
    values.update(overrides)
    return TradingConfig(**values)  # type: ignore[arg-type]


class FakeRiskAdapter:
    def __init__(self) -> None:
        self.positions: Sequence[dict[str, Any]] = []
        self.orders: Sequence[dict[str, Any]] = []
        self.free_collateral = 100.0

    async def fetch_positions(self) -> Sequence[dict[str, Any]]:
        return self.positions

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> Sequence[dict[str, Any]]:
        assert symbol is None
        return self.orders

    async def fetch_free_collateral(self) -> float:
        return self.free_collateral


def position(symbol: str, *, notional: float = 20.0) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "contracts": notional / 100,
        "markPrice": 100.0,
        "entryPrice": 100.0,
        "leverage": 5,
    }


def guard(
    adapter: FakeRiskAdapter,
    tmp_path: Path,
    **config_overrides: object,
) -> EntryRiskGuard:
    return EntryRiskGuard(
        adapter,
        config(**config_overrides),
        kill_switch_path=tmp_path / "ENTRY_KILL_SWITCH",
    )


@pytest.mark.asyncio
async def test_entry_within_all_limits_is_reserved_and_released(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    risk = guard(adapter, tmp_path)

    reservation = await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)
    assert reservation.notional == 10

    await risk.release(reservation)
    again = await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)
    assert again.reservation_id > reservation.reservation_id


@pytest.mark.asyncio
async def test_symbol_outside_allowlist_fails_closed(tmp_path: Path) -> None:
    adapter = FakeRiskAdapter()
    risk = guard(adapter, tmp_path)

    with pytest.raises(EntryRiskError, match="allowlist"):
        await risk.reserve_entry(
            symbol="SOL/USDC:USDC",
            amount=0.1,
            price=100,
        )


@pytest.mark.asyncio
async def test_existing_target_position_blocks_entry(tmp_path: Path) -> None:
    adapter = FakeRiskAdapter()
    adapter.positions = [position(BTC)]

    with pytest.raises(EntryRiskError, match="existing position"):
        await guard(adapter, tmp_path).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )


@pytest.mark.asyncio
async def test_invalid_or_out_of_allowlist_position_snapshot_fails_closed(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    adapter.positions = [position("SOL/USDC:USDC")]
    with pytest.raises(EntryRiskError, match="outside the allowlist"):
        await guard(adapter, tmp_path).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )

    adapter.positions = [position(ETH, notional=math.nan)]
    with pytest.raises(EntryRiskError, match="contracts must be finite"):
        await guard(adapter, tmp_path).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )


@pytest.mark.asyncio
async def test_restart_snapshot_counts_existing_other_position(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    adapter.positions = [position(ETH, notional=20)]
    adapter.orders = [
        {
            "symbol": ETH,
            "reduceOnly": True,
            "type": "stop",
        }
    ]

    reservation = await guard(adapter, tmp_path).reserve_entry(
        symbol=BTC,
        amount=0.1,
        price=100,
    )

    assert reservation.symbol == BTC


@pytest.mark.asyncio
async def test_orphan_or_pending_order_fails_closed(tmp_path: Path) -> None:
    adapter = FakeRiskAdapter()
    risk = guard(adapter, tmp_path)
    adapter.orders = [{"symbol": BTC, "reduceOnly": True, "type": "stop"}]
    with pytest.raises(EntryRiskError, match="orphan"):
        await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)

    adapter.orders = [{"symbol": BTC, "reduceOnly": False, "type": "limit"}]
    with pytest.raises(EntryRiskError, match="unsettled"):
        await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)


@pytest.mark.asyncio
async def test_order_total_position_and_balance_limits_fail_closed(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    with pytest.raises(EntryRiskError, match="max order"):
        await guard(adapter, tmp_path).reserve_entry(
            symbol=BTC,
            amount=0.21,
            price=100,
        )

    adapter.positions = [position(ETH, notional=45)]
    with pytest.raises(EntryRiskError, match="total notional"):
        await guard(
            adapter,
            tmp_path,
            max_symbol_notional_usdc=50.0,
        ).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )

    adapter.positions = [position(ETH, notional=20)]
    with pytest.raises(EntryRiskError, match="position count"):
        await guard(
            adapter,
            tmp_path,
            max_positions=1,
        ).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )

    adapter.positions = []
    adapter.free_collateral = 11.0
    with pytest.raises(EntryRiskError, match="free collateral"):
        await guard(adapter, tmp_path).reserve_entry(
            symbol=BTC,
            amount=0.1,
            price=100,
        )


@pytest.mark.asyncio
async def test_reservations_block_concentrated_or_multiple_signals(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    risk = guard(
        adapter,
        tmp_path,
        max_order_notional_usdc=10.0,
        max_symbol_notional_usdc=15.0,
        max_total_notional_usdc=19.0,
    )
    first = await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)

    with pytest.raises(EntryRiskError, match="symbol notional"):
        await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)
    with pytest.raises(EntryRiskError, match="total notional"):
        await risk.reserve_entry(symbol=ETH, amount=0.1, price=100)

    await risk.release(first)


@pytest.mark.asyncio
async def test_entry_kill_switch_does_not_touch_non_entry_execution(
    tmp_path: Path,
) -> None:
    adapter = FakeRiskAdapter()
    risk = guard(adapter, tmp_path)
    risk.stop_entries("operator request")

    with pytest.raises(EntryRiskError, match="operator request"):
        await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)

    # The guard has no close/protection API and therefore cannot inhibit those
    # paths. Its scope is intentionally entry-only.
    assert adapter.positions == []


@pytest.mark.asyncio
async def test_kill_switch_file_is_checked_on_every_entry(tmp_path: Path) -> None:
    adapter = FakeRiskAdapter()
    switch = tmp_path / "ENTRY_KILL_SWITCH"
    risk = EntryRiskGuard(adapter, config(), kill_switch_path=switch)
    switch.touch()

    with pytest.raises(EntryRiskError, match="kill-switch file"):
        await risk.reserve_entry(symbol=BTC, amount=0.1, price=100)
