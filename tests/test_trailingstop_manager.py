import math

import pytest

from crypto_spot_collector.exchange.trailingstop.trailingstop_manager import (
    TrailingStopManagerHyperLiquid,
    normalized_pnl_percentage,
    pnl_reaches_activation,
)
from crypto_spot_collector.exchange.types import PositionSide

SYMBOL = "ETH/USDC:USDC"


def add_position(
    manager: TrailingStopManagerHyperLiquid,
    *,
    side: PositionSide = PositionSide.LONG,
    entry_price: float = 100.0,
    contracts: float = 1.0,
    stoploss: float = 90.0,
    activated: bool = False,
) -> None:
    manager.add_or_update_position(
        symbol=SYMBOL,
        side=side,
        entry_price=entry_price,
        contracts=contracts,
        stoploss_order_id="stop-1",
        initial_stoploss_price=stoploss,
        trailing_activated=activated,
    )


@pytest.mark.parametrize(
    ("percentage", "unrealized_pnl", "expected"),
    [
        ("7.5", "10", 7.5),
        ("-7.5", "10", 7.5),
        ("7.5", "-10", -7.5),
        ("-7.5", "-10", -7.5),
        ("7.5", "0", 0.0),
    ],
)
def test_pnl_sign_is_normalized_from_unrealized_pnl(
    percentage: str,
    unrealized_pnl: str,
    expected: float,
) -> None:
    assert normalized_pnl_percentage(percentage, unrealized_pnl) == expected


def test_loss_never_reaches_trailing_activation() -> None:
    assert pnl_reaches_activation(-8, -10, 7) is False
    assert pnl_reaches_activation(8, -10, 7) is False
    assert pnl_reaches_activation(-8, 10, 7) is True


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_non_finite_pnl_snapshot_fails_closed(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        normalized_pnl_percentage(value, 1)


@pytest.mark.parametrize(
    ("entry_price", "contracts", "stoploss"),
    [
        (math.nan, 1.0, 90.0),
        (100.0, math.inf, 90.0),
        (100.0, 1.0, -math.inf),
        (0.0, 1.0, 90.0),
    ],
)
def test_invalid_position_snapshot_is_rejected(
    entry_price: float,
    contracts: float,
    stoploss: float,
) -> None:
    manager = TrailingStopManagerHyperLiquid()
    with pytest.raises(ValueError, match="finite and positive"):
        add_position(
            manager,
            entry_price=entry_price,
            contracts=contracts,
            stoploss=stoploss,
        )


def test_long_activates_at_breakeven_and_stop_only_moves_up() -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager)

    assert manager.activate_trailing(SYMBOL, current_price=110) is True
    position = manager.get_position(SYMBOL)
    assert position is not None
    assert position.current_stoploss_price == 100

    assert manager.update_stoploss_price(SYMBOL, current_price=120) is True
    raised_stop = position.current_stoploss_price
    assert raised_stop > 100
    assert manager.update_stoploss_price(SYMBOL, current_price=115) is False
    assert position.current_stoploss_price == raised_stop


def test_short_activates_at_breakeven_and_stop_only_moves_down() -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager, side=PositionSide.SHORT, stoploss=110)

    assert manager.activate_trailing(SYMBOL, current_price=90) is True
    position = manager.get_position(SYMBOL)
    assert position is not None
    assert position.current_stoploss_price == 100

    assert manager.update_stoploss_price(SYMBOL, current_price=80) is True
    lowered_stop = position.current_stoploss_price
    assert lowered_stop < 100
    assert manager.update_stoploss_price(SYMBOL, current_price=85) is False
    assert position.current_stoploss_price == lowered_stop


def test_activation_never_weakens_an_existing_protective_stop() -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager, stoploss=105)

    manager.activate_trailing(SYMBOL, current_price=110)

    position = manager.get_position(SYMBOL)
    assert position is not None
    assert position.current_stoploss_price == 105


def test_same_position_preserves_progress_and_adopts_tighter_exchange_stop() -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager)
    manager.activate_trailing(SYMBOL, current_price=110)
    manager.update_stoploss_price(SYMBOL, current_price=120)
    position = manager.get_position(SYMBOL)
    assert position is not None
    previous_high = position.highest_price
    previous_af = position.current_af_factor

    add_position(manager, stoploss=105, activated=True)

    position = manager.get_position(SYMBOL)
    assert position is not None
    assert position.highest_price == previous_high
    assert position.current_af_factor == previous_af
    assert position.current_stoploss_price == 105
    assert position.trailing_activated is True


@pytest.mark.parametrize(
    ("side", "entry_price", "contracts", "stoploss"),
    [
        (PositionSide.LONG, 101.0, 1.0, 90.0),
        (PositionSide.SHORT, 100.0, 1.0, 110.0),
        (PositionSide.LONG, 100.0, 0.5, 90.0),
    ],
)
def test_reentry_reverse_or_partial_close_resets_local_path_state(
    side: PositionSide,
    entry_price: float,
    contracts: float,
    stoploss: float,
) -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager)
    manager.activate_trailing(SYMBOL, current_price=110)
    manager.update_stoploss_price(SYMBOL, current_price=120)

    add_position(
        manager,
        side=side,
        entry_price=entry_price,
        contracts=contracts,
        stoploss=stoploss,
        activated=False,
    )

    position = manager.get_position(SYMBOL)
    assert position is not None
    assert position.side == side
    assert position.entry_price == entry_price
    assert position.contracts == contracts
    assert position.highest_price == entry_price
    assert position.lowest_price == entry_price
    assert position.current_af_factor == manager.initial_af_factor
    assert position.current_stoploss_price == stoploss
    assert position.trailing_activated is False


def test_exchange_snapshot_removes_flat_position_state() -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(manager)

    manager.remove_missing(set())

    assert manager.get_position(SYMBOL) is None


@pytest.mark.parametrize(
    ("side", "stoploss", "current_price", "comparison"),
    [
        (PositionSide.LONG, 105.0, 110.0, "higher"),
        (PositionSide.SHORT, 95.0, 90.0, "lower"),
    ],
)
def test_restart_restores_exchange_stop_without_regression(
    side: PositionSide,
    stoploss: float,
    current_price: float,
    comparison: str,
) -> None:
    manager = TrailingStopManagerHyperLiquid()
    add_position(
        manager,
        side=side,
        stoploss=stoploss,
        activated=True,
    )

    assert manager.update_stoploss_price(SYMBOL, current_price=current_price) is True
    position = manager.get_position(SYMBOL)
    assert position is not None
    if comparison == "higher":
        assert position.current_stoploss_price >= stoploss
    else:
        assert position.current_stoploss_price <= stoploss
