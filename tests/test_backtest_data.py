"""Tests for identity-aware historical candle input."""

from pathlib import Path

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import (
    CSVFormat,
    CandleDataError,
    CandleSeries,
    CandleSeriesKey,
    MarketType,
    load_ohlcv_csv,
    resample_ohlcv,
    validate_ohlcv,
)


def _minute_frame(count: int = 6) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=count, freq="1min", tz="UTC")
    opens = [100.0 + index for index in range(count)]
    closes = [value + 0.5 for value in opens]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": [value + 1.0 for value in opens],
            "low": [value - 1.0 for value in opens],
            "close": closes,
            "volume": [10.0 + index for index in range(count)],
        }
    )


def test_series_key_normalizes_complete_identity() -> None:
    key = CandleSeriesKey(" HyperLiquid ", "PERPETUAL", "eth/usdc:usdc", "1M")

    assert key.exchange == "hyperliquid"
    assert key.market_type is MarketType.PERPETUAL
    assert key.symbol == "ETH/USDC:USDC"
    assert key.timeframe == "1m"


def test_series_rejects_mixed_identity() -> None:
    frame = _minute_frame(2).assign(
        exchange=["hyperliquid", "binance"],
        market_type="perpetual",
        symbol="ETH/USDC:USDC",
        timeframe="1m",
    )
    key = CandleSeriesKey("hyperliquid", "perpetual", "ETH/USDC:USDC", "1m")

    with pytest.raises(CandleDataError, match="exchange contains mixed"):
        CandleSeries.from_frame(key, frame)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(index=2), "gap or wrong interval"),
        (
            lambda frame: pd.concat([frame, frame.iloc[[-1]]], ignore_index=True),
            "duplicates",
        ),
        (
            lambda frame: frame.assign(high=lambda value: value["open"] - 1),
            "bounds are inconsistent",
        ),
    ],
)
def test_validation_fails_closed(mutation: object, message: str) -> None:
    mutated = mutation(_minute_frame())  # type: ignore[operator]

    with pytest.raises(CandleDataError, match=message):
        validate_ohlcv(mutated, "1m")


def test_resample_aggregates_ohlcv_instead_of_sampling_boundaries() -> None:
    source = _minute_frame(6)

    result = resample_ohlcv(
        source,
        source_timeframe="1m",
        target_timeframe="3m",
    )

    assert result["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:03:00Z"),
    ]
    assert result.iloc[0].to_dict() == {
        "timestamp": pd.Timestamp("2026-01-01T00:00:00Z"),
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "close": 102.5,
        "volume": 33.0,
    }


def test_resample_rejects_partial_bucket() -> None:
    with pytest.raises(CandleDataError, match="incomplete"):
        resample_ohlcv(
            _minute_frame(5),
            source_timeframe="1m",
            target_timeframe="3m",
        )


def test_binance_kline_loader_infers_microsecond_timestamp(tmp_path: Path) -> None:
    csv_path = tmp_path / "eth.csv"
    csv_path.write_text(
        "1767225600000000,100,102,99,101,10,ignored\n"
        "1767225660000000,101,103,100,102,11,ignored\n",
        encoding="utf-8",
    )
    key = CandleSeriesKey("binance", "spot", "ETH/USDT", "1m")

    series = load_ohlcv_csv(
        csv_path,
        key=key,
        csv_format=CSVFormat.BINANCE_KLINES,
    )

    assert series.frame["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:01:00Z"),
    ]
    assert not series.funding_available
