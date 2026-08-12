from datetime import datetime, timezone

import pandas as pd
import pytest

from crypto_spot_collector.trading.strategy import (
    CandleGate,
    CandleIdentity,
    StrategyAction,
    StrategyState,
    StrategyStateMachine,
    latest_closed_identity,
)


def test_only_elapsed_candles_are_selected_and_claimed_once() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-13T00:00:00Z",
                "2026-08-13T00:30:00Z",
                "2026-08-13T01:00:00Z",
            ],
            "close": [1.0, 2.0, 3.0],
        }
    )
    selected, identity = latest_closed_identity(
        frame,
        symbol="BTC/USDC:USDC",
        timeframe="30m",
        now=datetime(2026, 8, 13, 1, 15, tzinfo=timezone.utc),
    )
    assert list(selected["close"]) == [1.0, 2.0]
    assert identity == CandleIdentity("BTC/USDC:USDC", "30m", 1786581000000)

    gate = CandleGate()
    assert gate.claim(identity) is True
    assert gate.claim(identity) is False


def test_gate_rejects_older_candle_after_newer_one() -> None:
    gate = CandleGate()
    assert gate.claim(CandleIdentity("BTC/USDC:USDC", "30m", 2)) is True
    assert gate.claim(CandleIdentity("BTC/USDC:USDC", "30m", 1)) is False


def test_close_reverse_requires_flat_confirmation() -> None:
    machine = StrategyStateMachine(StrategyState.LONG)
    assert machine.on_signal(StrategyState.SHORT) is StrategyAction.CLOSE_LONG
    assert machine.state is StrategyState.CLOSING_LONG
    assert machine.on_signal(StrategyState.SHORT) is StrategyAction.HOLD

    assert machine.confirm_flat() is StrategyAction.OPEN_SHORT
    assert machine.state is StrategyState.SHORT


def test_same_direction_does_not_add_position() -> None:
    machine = StrategyStateMachine(StrategyState.LONG)
    assert machine.on_signal(StrategyState.LONG) is StrategyAction.HOLD


def test_flat_confirmation_rejected_outside_close() -> None:
    with pytest.raises(RuntimeError):
        StrategyStateMachine().confirm_flat()
