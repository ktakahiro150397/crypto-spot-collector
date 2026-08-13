"""Closed-candle EMA/ADX entry-regime preparation for offline backtests."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from ta.trend import ADXIndicator, EMAIndicator

from crypto_spot_collector.trading.config import timeframe_milliseconds

from .data import CandleSeries, CandleSeriesKey, resample_ohlcv


class EntryFilterError(ValueError):
    """Raised when an entry filter cannot be prepared safely."""


@dataclass(frozen=True, order=True)
class EntryFilterConfig:
    """Higher-timeframe trend filter applied only to new SAR entries."""

    timeframe: str = "4h"
    ema_period: int = 50
    adx_period: int = 14
    adx_threshold: float | None = None

    @property
    def identifier(self) -> str:
        adx = (
            "off"
            if self.adx_threshold is None
            else f"{self.adx_period}:{self.adx_threshold:g}"
        )
        return f"{self.timeframe}|ema={self.ema_period}|adx={adx}"

    def validate(self, source_timeframe: str) -> None:
        if self.ema_period <= 1:
            raise EntryFilterError("EMA period must be greater than one")
        if self.adx_period <= 1:
            raise EntryFilterError("ADX period must be greater than one")
        if self.adx_threshold is not None and (
            not math.isfinite(self.adx_threshold) or self.adx_threshold < 0
        ):
            raise EntryFilterError("ADX threshold must be finite and non-negative")
        source_ms = _timeframe_ms(source_timeframe)
        filter_ms = _timeframe_ms(self.timeframe)
        if filter_ms <= source_ms or filter_ms % source_ms != 0:
            raise EntryFilterError(
                "entry-filter timeframe must be an integer multiple larger than "
                "source timeframe"
            )


@dataclass(frozen=True)
class PreparedEntryFilter:
    """Causal regime states keyed by the close time of each filter candle."""

    series_key: CandleSeriesKey
    source_start_ms: int
    source_end_ms: int
    source_candle_count: int
    config: EntryFilterConfig
    direction_by_close_ms: dict[int, str | None]


def prepare_entry_filter(
    series: CandleSeries,
    config: EntryFilterConfig,
) -> PreparedEntryFilter:
    """Build long/short permissions using only each completed filter candle."""

    config.validate(series.key.timeframe)
    candles = resample_ohlcv(
        series.frame,
        source_timeframe=series.key.timeframe,
        target_timeframe=config.timeframe,
    )
    ema = EMAIndicator(candles["close"], window=config.ema_period).ema_indicator()
    adx: pd.Series | None = None
    adx_threshold = config.adx_threshold
    if adx_threshold is not None:
        if len(candles) >= config.adx_period * 2:
            adx = ADXIndicator(
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                window=config.adx_period,
            ).adx()
        else:
            adx = pd.Series(float("nan"), index=candles.index)

    timeframe_ms = _timeframe_ms(config.timeframe)
    directions: dict[int, str | None] = {}
    for index, candle in candles.iterrows():
        close_ms = _timestamp_ms(candle["timestamp"]) + timeframe_ms
        ema_value = float(ema.iloc[index])
        direction: str | None = None
        if math.isfinite(ema_value):
            adx_ready = True
            if adx is not None:
                assert adx_threshold is not None
                adx_value = float(adx.iloc[index])
                adx_ready = (
                    index >= config.adx_period * 2 - 1
                    and math.isfinite(adx_value)
                    and adx_value >= adx_threshold
                )
            if adx_ready:
                close = float(candle["close"])
                if close > ema_value:
                    direction = "long"
                elif close < ema_value:
                    direction = "short"
        directions[close_ms] = direction

    return PreparedEntryFilter(
        series_key=series.key,
        source_start_ms=_timestamp_ms(series.frame.iloc[0]["timestamp"]),
        source_end_ms=_timestamp_ms(series.frame.iloc[-1]["timestamp"]),
        source_candle_count=len(series.frame),
        config=config,
        direction_by_close_ms=directions,
    )


def _timeframe_ms(timeframe: str) -> int:
    try:
        return int(timeframe_milliseconds(timeframe))
    except ValueError as exc:
        raise EntryFilterError(str(exc)) from exc


def _timestamp_ms(value: object) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)
