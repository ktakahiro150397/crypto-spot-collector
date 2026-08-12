from datetime import datetime, timezone

import pandas as pd
import pytest

from crypto_spot_collector.trading.strategy import (
    CandleGate,
    CandleIdentity,
    SQLiteSarStateStore,
    StrategyAction,
    StrategyState,
    StrategyStateMachine,
    SarSignalDecision,
    evaluate_sar_signal,
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


@pytest.mark.parametrize(
    "timestamps, message",
    [
        (
            ["2026-08-13T00:30:00Z", "2026-08-13T00:30:00Z"],
            "duplicates",
        ),
        (
            ["2026-08-13T00:30:00Z", "2026-08-13T00:00:00Z"],
            "strictly increasing",
        ),
    ],
)
def test_latest_closed_identity_rejects_duplicate_or_reversed_candles(
    timestamps: list[str], message: str
) -> None:
    frame = pd.DataFrame({"timestamp": timestamps, "close": [1.0, 2.0]})
    with pytest.raises(ValueError, match=message):
        latest_closed_identity(
            frame,
            symbol="BTC/USDC:USDC",
            timeframe="30m",
            now=datetime(2026, 8, 13, 1, 0, tzinfo=timezone.utc),
        )


def test_latest_closed_identity_rejects_stale_or_gapped_tail() -> None:
    stale = pd.DataFrame({"timestamp": ["2026-08-13T00:00:00Z"], "close": [1.0]})
    with pytest.raises(ValueError, match="missing or stale"):
        latest_closed_identity(
            stale,
            symbol="BTC/USDC:USDC",
            timeframe="30m",
            now=datetime(2026, 8, 13, 1, 15, tzinfo=timezone.utc),
        )

    gapped = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-12T23:30:00Z",
                "2026-08-13T00:30:00Z",
            ],
            "close": [1.0, 2.0],
        }
    )
    with pytest.raises(ValueError, match="gap"):
        latest_closed_identity(
            gapped,
            symbol="BTC/USDC:USDC",
            timeframe="30m",
            now=datetime(2026, 8, 13, 1, 15, tzinfo=timezone.utc),
            required_rows=2,
        )


def test_latest_closed_identity_requires_indicator_warmup_rows() -> None:
    frame = pd.DataFrame({"timestamp": ["2026-08-13T00:30:00Z"], "close": [1.0]})
    with pytest.raises(ValueError, match="warm-up"):
        latest_closed_identity(
            frame,
            symbol="BTC/USDC:USDC",
            timeframe="30m",
            now=datetime(2026, 8, 13, 1, 15, tzinfo=timezone.utc),
            required_rows=2,
        )


def test_sar_progress_persists_counter_and_rejects_same_candle(tmp_path) -> None:
    database = tmp_path / "runtime.sqlite"
    first_store = SQLiteSarStateStore(database)
    first = first_store.advance(
        candle=CandleIdentity("BTC/USDC:USDC", "30m", 1),
        direction="short",
        position_side="long",
    )
    assert first is not None
    assert first.opposite_count == 1

    restarted_store = SQLiteSarStateStore(database)
    assert (
        restarted_store.advance(
            candle=CandleIdentity("BTC/USDC:USDC", "30m", 1),
            direction="short",
            position_side="long",
        )
        is None
    )
    second = restarted_store.advance(
        candle=CandleIdentity("BTC/USDC:USDC", "30m", 2),
        direction="short",
        position_side="long",
    )
    assert second is not None
    assert second.previous_direction == "short"
    assert second.opposite_count == 2

    aligned = restarted_store.advance(
        candle=CandleIdentity("BTC/USDC:USDC", "30m", 3),
        direction="long",
        position_side="long",
    )
    assert aligned is not None
    assert aligned.opposite_count == 0


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


def test_sar_signal_evaluation_is_a_shared_pure_decision() -> None:
    class Checker:
        def get_current_sar_direction(self, df: pd.DataFrame) -> str | None:
            return "long"

        def check_long(self, df: pd.DataFrame, **kwargs: object) -> bool:
            return True

        def check_short(self, df: pd.DataFrame, **kwargs: object) -> bool:
            return False

    frame = pd.DataFrame({"sar_up": [1.0], "sar_down": [float("nan")]})

    assert evaluate_sar_signal(frame, Checker()) == SarSignalDecision(
        direction="long",
        long_signal=True,
        short_signal=False,
    )
