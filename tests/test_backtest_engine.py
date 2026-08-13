"""Deterministic execution tests for the perpetual SAR backtester."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import CandleSeries, CandleSeriesKey
from crypto_spot_collector.backtesting.engine import (
    BacktestConfig,
    BacktestConfigError,
    PerpetualSarBacktester,
)
from crypto_spot_collector.backtesting.regime import (
    EntryFilterConfig,
    PreparedEntryFilter,
)
from crypto_spot_collector.trading.strategy import SarSignalDecision


def _series(
    rows: list[dict[str, float]],
    *,
    exchange: str = "hyperliquid",
) -> CandleSeries:
    frame = pd.DataFrame(rows)
    frame.insert(
        0,
        "timestamp",
        pd.date_range("2026-01-01", periods=len(frame), freq="1min", tz="UTC"),
    )
    if "volume" not in frame:
        frame["volume"] = 1.0
    symbol = "ETH/USDC:USDC" if exchange == "hyperliquid" else "ETH/USDT:USDT"
    key = CandleSeriesKey(exchange, "perpetual", symbol, "1m")
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


def _entry_filter(
    series: CandleSeries,
    directions: dict[int, str | None],
) -> PreparedEntryFilter:
    timestamps = series.frame["timestamp"]
    return PreparedEntryFilter(
        series_key=series.key,
        source_start_ms=int(pd.Timestamp(timestamps.iloc[0]).timestamp() * 1_000),
        source_end_ms=int(pd.Timestamp(timestamps.iloc[-1]).timestamp() * 1_000),
        source_candle_count=len(series.frame),
        config=EntryFilterConfig(),
        direction_by_close_ms=directions,
    )


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


def test_binance_proxy_requires_explicit_permission_and_marks_summary() -> None:
    series = _series(_flat_rows(2), exchange="binance")

    with pytest.raises(BacktestConfigError, match="explicit allow_proxy_data"):
        PerpetualSarBacktester(_config()).run(series)

    result = PerpetualSarBacktester(
        _config(allow_proxy_data=True),
        signal_evaluator=_evaluator({}),
    ).run(series)
    assert result.summary["strategy_exchange"] == "hyperliquid"
    assert result.summary["data_mode"] == "proxy"
    assert "Binance prices" in str(result.summary["proxy_warning"])


def test_prepared_sar_signals_are_reusable_and_configuration_checked() -> None:
    series = _series(_flat_rows(4))
    evaluator = _evaluator({"00:00": SarSignalDecision("long", True, False)})
    backtester = PerpetualSarBacktester(_config(), signal_evaluator=evaluator)
    prepared = backtester.prepare_signals(series)

    cached = backtester.run(series, prepared_signals=prepared)
    uncached = backtester.run(series)

    pd.testing.assert_frame_equal(cached.trades, uncached.trades)
    pd.testing.assert_frame_equal(cached.equity_curve, uncached.equity_curve)

    mismatched = PerpetualSarBacktester(
        _config(signal_timeframe="2m"),
        signal_evaluator=evaluator,
    )
    with pytest.raises(BacktestConfigError, match="prepared SAR signals"):
        mismatched.run(series, prepared_signals=prepared)

    other_period = _series(_flat_rows(5))
    with pytest.raises(BacktestConfigError, match="prepared SAR signals"):
        backtester.run(other_period, prepared_signals=prepared)


def test_entry_filter_blocks_only_new_entries_and_records_signal_counts() -> None:
    series = _series(_flat_rows(4))
    evaluator = _evaluator(
        {
            "00:00": SarSignalDecision("long", True, False),
            "00:01": SarSignalDecision("short", False, False),
            "00:02": SarSignalDecision("short", False, False),
        }
    )
    backtester = PerpetualSarBacktester(_config(), signal_evaluator=evaluator)
    first_close_ms = int(pd.Timestamp("2026-01-01T00:01:00Z").timestamp() * 1_000)

    blocked = backtester.run(
        series,
        prepared_entry_filter=_entry_filter(series, {first_close_ms: "short"}),
    )
    allowed = backtester.run(
        series,
        prepared_entry_filter=_entry_filter(series, {first_close_ms: "long"}),
    )

    assert blocked.trades.empty
    assert blocked.summary["entry_signal_count"] == 1
    assert blocked.summary["filtered_entry_signal_count"] == 1
    assert allowed.trades.iloc[0]["exit_reason"] == "opposite_sar"
    assert allowed.summary["entry_signal_count"] == 1
    assert allowed.summary["filtered_entry_signal_count"] == 0


def test_entry_filter_must_match_the_execution_series() -> None:
    series = _series(_flat_rows(3))
    other = _series(_flat_rows(4))
    prepared = _entry_filter(other, {})

    with pytest.raises(BacktestConfigError, match="entry filter"):
        PerpetualSarBacktester(_config()).run(
            series,
            prepared_entry_filter=prepared,
        )
