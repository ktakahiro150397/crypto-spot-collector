"""Tests for causal comparative technical-strategy signals."""

from __future__ import annotations

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import CandleSeries, CandleSeriesKey
from crypto_spot_collector.backtesting.strategy_signals import (
    SideMode,
    StrategyFamily,
    StrategySignalError,
    StrategySpec,
    _align_closed_filter,
    prepare_strategy_signals,
)


def _series(closes: list[float]) -> CandleSeries:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2025-01-01", periods=len(closes), freq="1h", tz="UTC"
            ),
            "open": closes,
            "high": [value + 0.5 for value in closes],
            "low": [value - 0.5 for value in closes],
            "close": closes,
            "volume": 1.0,
        }
    )
    return CandleSeries.from_frame(
        CandleSeriesKey("binance", "perpetual", "ETH/USDT:USDT", "1h"),
        frame,
    )


def _decisions(series: CandleSeries, spec: StrategySpec) -> list[object]:
    return list(prepare_strategy_signals(series, spec).decisions_by_close_ms.values())


def test_ema_price_signal_uses_closed_candles_and_confirms_once() -> None:
    spec = StrategySpec(
        StrategyFamily.EMA_PRICE,
        "1h",
        ema_period=3,
        confirmation=2,
    )
    decisions = _decisions(_series([100, 99, 98, 99, 100, 101]), spec)

    long_indexes = [index for index, item in enumerate(decisions) if item.long_signal]
    assert long_indexes == [4]
    assert decisions[4].direction == "long"


def test_future_prices_cannot_change_existing_ema_decisions() -> None:
    spec = StrategySpec(StrategyFamily.EMA_CROSS, "1h", fast_period=2, slow_period=4)
    common = [100.0, 99.0, 98.0, 99.0, 101.0, 103.0]
    rising = _decisions(_series(common + [110.0, 120.0]), spec)
    falling = _decisions(_series(common + [90.0, 80.0]), spec)

    assert rising[: len(common)] == falling[: len(common)]


def test_donchian_uses_prior_channel_and_short_only_suppresses_long_entries() -> None:
    spec = StrategySpec(
        StrategyFamily.DONCHIAN,
        "1h",
        side_mode=SideMode.SHORT_ONLY,
        lookback=3,
    )
    decisions = _decisions(_series([100, 100, 100, 102, 98, 96]), spec)

    assert not any(item.long_signal for item in decisions)
    assert any(item.short_signal for item in decisions)


def test_atr_filter_blocks_entries_below_requested_volatility() -> None:
    closes = [100.0 + index * 0.01 for index in range(40)]
    unfiltered = StrategySpec(
        StrategyFamily.EMA_PRICE,
        "1h",
        ema_period=3,
    )
    filtered = StrategySpec(
        StrategyFamily.EMA_PRICE,
        "1h",
        ema_period=3,
        atr_min_percent=5.0,
    )

    assert any(item.long_signal for item in _decisions(_series(closes), unfiltered))
    assert not any(item.long_signal for item in _decisions(_series(closes), filtered))


def test_invalid_strategy_periods_are_rejected() -> None:
    with pytest.raises(StrategySignalError, match="1 < fast < slow"):
        StrategySpec(
            StrategyFamily.EMA_CROSS,
            "1h",
            fast_period=20,
            slow_period=10,
        ).validate("1h")


def test_higher_timeframe_filter_is_available_only_after_its_close() -> None:
    signal_candles = _series([100.0] * 8).frame
    filter_candles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=2, freq="4h", tz="UTC"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )

    aligned = _align_closed_filter(
        signal_candles,
        filter_candles,
        pd.Series([False, True]),
        signal_timeframe="1h",
        filter_timeframe="4h",
    )

    assert not aligned.iloc[6]
    assert aligned.iloc[7]
