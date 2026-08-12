"""Deterministic execution tests for the perpetual SAR backtester."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import CandleSeries, CandleSeriesKey
from crypto_spot_collector.backtesting.engine import (
    BacktestConfig,
    PerpetualSarBacktester,
)
from crypto_spot_collector.trading.strategy import SarSignalDecision


def _series(rows: list[dict[str, float]]) -> CandleSeries:
    frame = pd.DataFrame(rows)
    frame.insert(
        0,
        "timestamp",
        pd.date_range("2026-01-01", periods=len(frame), freq="1min", tz="UTC"),
    )
    if "volume" not in frame:
        frame["volume"] = 1.0
    key = CandleSeriesKey("hyperliquid", "perpetual", "ETH/USDC:USDC", "1m")
    return CandleSeries.from_frame(key, frame)


def _flat_rows(count: int, price: float = 100.0) -> list[dict[str, float]]:
    return [
        {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }
        for _ in range(count)
    ]


def _evaluator(
    decisions: dict[str, SarSignalDecision],
    default_direction: str = "long",
) -> Callable[[pd.DataFrame], SarSignalDecision]:
    def evaluate(frame: pd.DataFrame) -> SarSignalDecision:
        timestamp = pd.Timestamp(frame.iloc[-1]["timestamp"]).strftime("%H:%M")
        return decisions.get(
            timestamp,
            SarSignalDecision(default_direction, False, False),
        )

    return evaluate


def _config(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = {
        "signal_timeframe": "1m",
        "initial_equity": 1_000.0,
        "order_notional": 100.0,
        "leverage": 1,
        "take_profit_roe": 20.0,
        "stop_loss_roe": 20.0,
        "trailing_activation_roe": 10.0,
        "trailing_interval_minutes": 1,
        "sar_consecutive_count": 1,
        "sar_close_consecutive_count": 2,
        "taker_fee_bps": 0.0,
        "slippage_bps": 0.0,
    }
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def test_signal_fills_at_next_open_with_adverse_slippage_and_fees() -> None:
    series = _series(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100},
            {"open": 101, "high": 102, "low": 101, "close": 102},
            {"open": 103, "high": 104, "low": 103, "close": 104},
        ]
    )
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    result = PerpetualSarBacktester(
        _config(taker_fee_bps=10.0, slippage_bps=10.0),
        signal_evaluator=evaluator,
    ).run(series)

    trade = result.trades.iloc[0]
    assert trade["entry_time"] == "2026-01-01T00:01:00+00:00"
    assert trade["entry_price"] == pytest.approx(101.101)
    assert trade["exit_time"] == "2026-01-01T00:03:00+00:00"
    assert trade["exit_price"] == pytest.approx(103.896)
    assert trade["exit_reason"] == "end_of_data"
    assert trade["net_pnl"] < trade["gross_pnl"]


def test_same_candle_take_profit_and_stop_loss_uses_stop_first() -> None:
    series = _series(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100},
            {"open": 100, "high": 102, "low": 98, "close": 100},
        ]
    )
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    result = PerpetualSarBacktester(
        _config(
            take_profit_roe=1.0,
            stop_loss_roe=1.0,
            trailing_activation_roe=0.5,
        ),
        signal_evaluator=evaluator,
    ).run(series)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(99.0)


def test_short_take_profit_uses_protective_trigger() -> None:
    series = _series(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100},
            {"open": 100, "high": 100, "low": 98, "close": 99},
        ]
    )
    evaluator = _evaluator(
        {"00:00": SarSignalDecision("short", False, True)},
        default_direction="short",
    )
    result = PerpetualSarBacktester(
        _config(
            take_profit_roe=1.0,
            stop_loss_roe=5.0,
            trailing_activation_roe=0.5,
        ),
        signal_evaluator=evaluator,
    ).run(series)

    trade = result.trades.iloc[0]
    assert trade["side"] == "short"
    assert trade["exit_reason"] == "take_profit"
    assert trade["exit_price"] == pytest.approx(99.0)


def test_consecutive_opposite_sar_closes_at_following_open() -> None:
    evaluator = _evaluator(
        {
            "00:00": SarSignalDecision("long", True, False),
            "00:01": SarSignalDecision("short", False, False),
            "00:02": SarSignalDecision("short", False, False),
        }
    )
    result = PerpetualSarBacktester(_config(), signal_evaluator=evaluator).run(
        _series(_flat_rows(4))
    )

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "opposite_sar"
    assert trade["exit_time"] == "2026-01-01T00:03:00+00:00"


def test_positive_funding_is_charged_to_long() -> None:
    rows = _flat_rows(2)
    rows[0]["funding_rate"] = 0.0
    rows[1]["funding_rate"] = 0.01
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    result = PerpetualSarBacktester(_config(), signal_evaluator=evaluator).run(
        _series(rows)
    )

    trade = result.trades.iloc[0]
    assert trade["funding"] == pytest.approx(1.0)
    assert trade["net_pnl"] == pytest.approx(-1.0)
    assert result.summary["funding_included"] is True


def test_trailing_stop_activates_then_becomes_effective_next_candle() -> None:
    series = _series(
        [
            {"open": 100, "high": 100, "low": 100, "close": 100},
            {"open": 100, "high": 102, "low": 99.5, "close": 102},
            {"open": 102, "high": 103, "low": 101, "close": 103},
            {"open": 103, "high": 103, "low": 100, "close": 100.5},
        ]
    )
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    result = PerpetualSarBacktester(
        _config(
            take_profit_roe=50.0,
            stop_loss_roe=10.0,
            trailing_activation_roe=1.0,
        ),
        signal_evaluator=evaluator,
    ).run(series)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit_price"] == pytest.approx(100.06)
    assert trade["exit_time"] == "2026-01-01T00:03:00+00:00"


def test_metrics_report_drawdown_and_profit_factor() -> None:
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    result = PerpetualSarBacktester(_config(), signal_evaluator=evaluator).run(
        _series(_flat_rows(2))
    )

    assert result.summary["trade_count"] == 1
    assert result.summary["final_equity"] == pytest.approx(1_000.0)
    assert result.summary["max_drawdown_percent"] == pytest.approx(0.0)
    assert result.summary["profit_factor"] is None


def test_no_signal_still_returns_a_stable_empty_trade_ledger() -> None:
    result = PerpetualSarBacktester(_config(), signal_evaluator=_evaluator({})).run(
        _series(_flat_rows(2))
    )

    assert result.trades.empty
    assert result.trades.columns.tolist() == [
        "entry_time",
        "exit_time",
        "side",
        "entry_price",
        "exit_price",
        "quantity",
        "gross_pnl",
        "entry_fee",
        "exit_fee",
        "funding",
        "net_pnl",
        "exit_reason",
    ]
