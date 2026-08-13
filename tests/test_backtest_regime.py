"""Tests for causal higher-timeframe EMA/ADX entry filters."""

from __future__ import annotations

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import CandleSeries, CandleSeriesKey
from crypto_spot_collector.backtesting.regime import (
    EntryFilterConfig,
    EntryFilterError,
    prepare_entry_filter,
)


def _hourly_series(closes: list[float]) -> CandleSeries:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2025-01-01", periods=len(closes), freq="1h", tz="UTC"
            ),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": 1.0,
        }
    )
    return CandleSeries.from_frame(
        CandleSeriesKey("binance", "perpetual", "ETH/USDT:USDT", "1h"),
        frame,
    )


def _close_ms(timestamp: str) -> int:
    return int(pd.Timestamp(timestamp).timestamp() * 1_000)


def test_ema_filter_is_published_only_when_each_four_hour_candle_closes() -> None:
    prepared = prepare_entry_filter(
        _hourly_series([float(value) for value in range(100, 112)]),
        EntryFilterConfig(timeframe="4h", ema_period=2),
    )

    assert sorted(prepared.direction_by_close_ms) == [
        _close_ms("2025-01-01T04:00:00Z"),
        _close_ms("2025-01-01T08:00:00Z"),
        _close_ms("2025-01-01T12:00:00Z"),
    ]
    assert prepared.direction_by_close_ms[_close_ms("2025-01-01T04:00:00Z")] is None
    assert prepared.direction_by_close_ms[_close_ms("2025-01-01T08:00:00Z")] == "long"


def test_future_prices_cannot_change_an_already_closed_regime() -> None:
    common = [float(value) for value in range(100, 108)]
    rising = prepare_entry_filter(
        _hourly_series(common + [108.0, 109.0, 110.0, 111.0]),
        EntryFilterConfig(timeframe="4h", ema_period=2),
    )
    falling = prepare_entry_filter(
        _hourly_series(common + [80.0, 79.0, 78.0, 77.0]),
        EntryFilterConfig(timeframe="4h", ema_period=2),
    )

    close = _close_ms("2025-01-01T08:00:00Z")
    assert rising.direction_by_close_ms[close] == falling.direction_by_close_ms[close]


def test_adx_filter_waits_for_warmup_and_allows_a_strong_trend() -> None:
    closes = [100.0 + index * 0.5 for index in range(28 * 4)]
    prepared = prepare_entry_filter(
        _hourly_series(closes),
        EntryFilterConfig(
            timeframe="4h",
            ema_period=20,
            adx_period=14,
            adx_threshold=20.0,
        ),
    )
    directions = list(prepared.direction_by_close_ms.values())

    assert all(direction is None for direction in directions[:27])
    assert directions[-1] == "long"


def test_entry_filter_rejects_invalid_periods_and_timeframes() -> None:
    with pytest.raises(EntryFilterError, match="EMA period"):
        EntryFilterConfig(ema_period=1).validate("1m")
    with pytest.raises(EntryFilterError, match="integer multiple larger"):
        EntryFilterConfig(timeframe="1m").validate("1m")
