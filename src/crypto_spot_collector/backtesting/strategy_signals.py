"""Causal technical-strategy signals for comparative offline backtests."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, PSARIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from crypto_spot_collector.trading.config import timeframe_milliseconds
from crypto_spot_collector.trading.strategy import SarSignalDecision

from .data import CandleSeries, resample_ohlcv
from .engine import PreparedStrategySignals


class StrategySignalError(ValueError):
    """Raised when a strategy specification cannot be prepared safely."""


class StrategyFamily(StrEnum):
    SAR = "sar"
    EMA_PRICE = "ema_price"
    EMA_CROSS = "ema_cross"
    DONCHIAN = "donchian"
    MOMENTUM = "momentum"
    RSI_BOLLINGER = "rsi_bollinger"


class SideMode(StrEnum):
    BOTH = "both"
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"


@dataclass(frozen=True)
class StrategySpec:
    """One immutable signal definition in the pre-registered search grid."""

    family: StrategyFamily | str
    signal_timeframe: str
    side_mode: SideMode | str = SideMode.BOTH
    filter_timeframe: str | None = None
    confirmation: int = 1
    sar_consecutive_count: int = 4
    ema_period: int | None = None
    fast_period: int | None = None
    slow_period: int | None = None
    lookback: int | None = None
    momentum_threshold: float = 0.0
    adx_period: int = 14
    adx_threshold: float | None = None
    atr_period: int = 14
    atr_min_percent: float | None = None
    rsi_period: int = 14
    rsi_lower: float = 30.0
    rsi_upper: float = 70.0
    bollinger_period: int = 20
    bollinger_deviation: float = 2.0

    def __post_init__(self) -> None:
        try:
            family = StrategyFamily(str(self.family).lower())
        except ValueError as exc:
            raise StrategySignalError(
                f"unsupported strategy family: {self.family}"
            ) from exc
        try:
            side_mode = SideMode(str(self.side_mode).lower())
        except ValueError as exc:
            raise StrategySignalError(
                f"unsupported side mode: {self.side_mode}"
            ) from exc
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "side_mode", side_mode)
        object.__setattr__(self, "signal_timeframe", self.signal_timeframe.lower())
        if self.filter_timeframe is not None:
            object.__setattr__(self, "filter_timeframe", self.filter_timeframe.lower())

    @property
    def identifier(self) -> str:
        family = StrategyFamily(self.family)
        side_mode = SideMode(self.side_mode)
        fields = [
            family.value,
            f"tf={self.signal_timeframe}",
            f"side={side_mode.value}",
        ]
        if family is StrategyFamily.SAR:
            fields.append(f"count={self.sar_consecutive_count}")
            if self.ema_period is not None:
                fields.append(f"ema={self.ema_period}")
        elif family is StrategyFamily.EMA_PRICE:
            fields.extend([f"ema={self.ema_period}", f"confirm={self.confirmation}"])
        elif family is StrategyFamily.EMA_CROSS:
            fields.extend(
                [
                    f"ema={self.fast_period}:{self.slow_period}",
                    f"confirm={self.confirmation}",
                ]
            )
        elif family is StrategyFamily.DONCHIAN:
            fields.extend([f"lookback={self.lookback}", f"confirm={self.confirmation}"])
        elif family is StrategyFamily.MOMENTUM:
            fields.extend(
                [
                    f"lookback={self.lookback}",
                    f"threshold={self.momentum_threshold:g}",
                    f"confirm={self.confirmation}",
                ]
            )
        else:
            fields.extend(
                [
                    f"rsi={self.rsi_period}:{self.rsi_lower:g}:{self.rsi_upper:g}",
                    f"bb={self.bollinger_period}:{self.bollinger_deviation:g}",
                ]
            )
        if self.adx_threshold is not None:
            fields.append(f"adx={self.adx_period}:{self.adx_threshold:g}")
        if self.atr_min_percent is not None:
            fields.append(f"atr={self.atr_period}:{self.atr_min_percent:g}")
        if self.filter_timeframe is not None:
            fields.append(f"filter_tf={self.filter_timeframe}")
        return "|".join(fields)

    def as_dict(self) -> dict[str, object]:
        return {
            "family": StrategyFamily(self.family).value,
            "signal_timeframe": self.signal_timeframe,
            "side_mode": SideMode(self.side_mode).value,
            "filter_timeframe": self.filter_timeframe,
            "confirmation": self.confirmation,
            "sar_consecutive_count": self.sar_consecutive_count,
            "ema_period": self.ema_period,
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "lookback": self.lookback,
            "momentum_threshold": self.momentum_threshold,
            "adx_period": self.adx_period,
            "adx_threshold": self.adx_threshold,
            "atr_period": self.atr_period,
            "atr_min_percent": self.atr_min_percent,
            "rsi_period": self.rsi_period,
            "rsi_lower": self.rsi_lower,
            "rsi_upper": self.rsi_upper,
            "bollinger_period": self.bollinger_period,
            "bollinger_deviation": self.bollinger_deviation,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "StrategySpec":
        return cls(**values)

    def validate(self, source_timeframe: str) -> None:
        source_ms = _timeframe_ms(source_timeframe)
        signal_ms = _timeframe_ms(self.signal_timeframe)
        if signal_ms < source_ms or signal_ms % source_ms != 0:
            raise StrategySignalError(
                "signal timeframe must be an integer multiple of source timeframe"
            )
        if self.filter_timeframe is not None:
            filter_ms = _timeframe_ms(self.filter_timeframe)
            if filter_ms < signal_ms or filter_ms % signal_ms != 0:
                raise StrategySignalError(
                    "filter timeframe must be an integer multiple of signal timeframe"
                )
        if self.confirmation <= 0:
            raise StrategySignalError("confirmation must be positive")
        if self.sar_consecutive_count <= 0:
            raise StrategySignalError("SAR consecutive count must be positive")
        for name, value in (
            ("adx_period", self.adx_period),
            ("atr_period", self.atr_period),
            ("rsi_period", self.rsi_period),
            ("bollinger_period", self.bollinger_period),
        ):
            if value <= 1:
                raise StrategySignalError(f"{name} must be greater than one")
        for name, threshold_value in (
            ("adx_threshold", self.adx_threshold),
            ("atr_min_percent", self.atr_min_percent),
        ):
            if threshold_value is not None and (
                not math.isfinite(threshold_value) or threshold_value < 0
            ):
                raise StrategySignalError(f"{name} must be finite and non-negative")

        if self.family in {StrategyFamily.SAR, StrategyFamily.EMA_PRICE}:
            if self.family is StrategyFamily.EMA_PRICE and self.ema_period is None:
                raise StrategySignalError("EMA-price strategy requires ema_period")
            if self.ema_period is not None and self.ema_period <= 1:
                raise StrategySignalError("ema_period must be greater than one")
        elif self.family is StrategyFamily.EMA_CROSS:
            if self.fast_period is None or self.slow_period is None:
                raise StrategySignalError("EMA-cross strategy requires both periods")
            if self.fast_period <= 1 or self.fast_period >= self.slow_period:
                raise StrategySignalError("EMA periods must satisfy 1 < fast < slow")
        elif self.family in {StrategyFamily.DONCHIAN, StrategyFamily.MOMENTUM}:
            if self.lookback is None or self.lookback <= 1:
                raise StrategySignalError("strategy lookback must be greater than one")
            if (
                not math.isfinite(self.momentum_threshold)
                or self.momentum_threshold < 0
            ):
                raise StrategySignalError(
                    "momentum threshold must be finite and non-negative"
                )
        elif not (0 < self.rsi_lower < 50 < self.rsi_upper < 100):
            raise StrategySignalError("RSI thresholds must straddle 50")
        if not math.isfinite(self.bollinger_deviation) or self.bollinger_deviation <= 0:
            raise StrategySignalError("Bollinger deviation must be finite and positive")


def prepare_strategy_signals(
    series: CandleSeries,
    spec: StrategySpec,
) -> PreparedStrategySignals:
    """Calculate closed-candle decisions without using future candles."""

    spec.validate(series.key.timeframe)
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    if spec.signal_timeframe == series.key.timeframe:
        candles = series.frame.loc[:, columns].copy()
    else:
        candles = resample_ohlcv(
            series.frame,
            source_timeframe=series.key.timeframe,
            target_timeframe=spec.signal_timeframe,
        )

    direction, long_entry, short_entry = _core_signals(candles, spec)
    permission_candles = _permission_candles(series, candles, spec)
    allowed = _entry_permissions(permission_candles, spec)
    if permission_candles is not candles:
        allowed = {
            side: _align_closed_filter(
                candles,
                permission_candles,
                values,
                signal_timeframe=spec.signal_timeframe,
                filter_timeframe=spec.filter_timeframe,
            )
            for side, values in allowed.items()
        }
    long_entry &= allowed["long"]
    short_entry &= allowed["short"]
    if spec.side_mode is SideMode.LONG_ONLY:
        short_entry[:] = False
    elif spec.side_mode is SideMode.SHORT_ONLY:
        long_entry[:] = False

    timeframe_ms = _timeframe_ms(spec.signal_timeframe)
    decisions: dict[int, SarSignalDecision] = {}
    for timestamp, raw_direction, is_long, is_short in zip(
        candles["timestamp"],
        direction,
        long_entry,
        short_entry,
        strict=True,
    ):
        close_ms = _timestamp_ms(timestamp) + timeframe_ms
        normalized_direction = (
            str(raw_direction) if raw_direction in {"long", "short"} else None
        )
        decisions[close_ms] = SarSignalDecision(
            direction=normalized_direction,
            long_signal=bool(is_long),
            short_signal=bool(is_short),
        )

    return PreparedStrategySignals(
        series_key=series.key,
        source_start_ms=_timestamp_ms(series.frame.iloc[0]["timestamp"]),
        source_end_ms=_timestamp_ms(series.frame.iloc[-1]["timestamp"]),
        source_candle_count=len(series.frame),
        signal_timeframe=spec.signal_timeframe,
        strategy_id=spec.identifier,
        decisions_by_close_ms=decisions,
    )


def _core_signals(
    candles: pd.DataFrame,
    spec: StrategySpec,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = candles["close"].astype(float)
    empty_direction = pd.Series(None, index=candles.index, dtype="object")

    if spec.family is StrategyFamily.SAR:
        indicator = PSARIndicator(
            high=candles["high"],
            low=candles["low"],
            close=close,
        )
        up = indicator.psar_up()
        down = indicator.psar_down()
        direction = empty_direction.copy()
        direction.loc[up.notna() & down.isna()] = "long"
        direction.loc[down.notna() & up.isna()] = "short"
        return (
            direction,
            _run_reached(direction, "long", spec.sar_consecutive_count),
            _run_reached(direction, "short", spec.sar_consecutive_count),
        )

    if spec.family is StrategyFamily.EMA_PRICE:
        assert spec.ema_period is not None
        ema = EMAIndicator(close, window=spec.ema_period).ema_indicator()
        direction = empty_direction.copy()
        direction.loc[ema.notna() & (close > ema)] = "long"
        direction.loc[ema.notna() & (close < ema)] = "short"
        return _trend_entries(direction, spec.confirmation)

    if spec.family is StrategyFamily.EMA_CROSS:
        assert spec.fast_period is not None and spec.slow_period is not None
        fast = EMAIndicator(close, window=spec.fast_period).ema_indicator()
        slow = EMAIndicator(close, window=spec.slow_period).ema_indicator()
        ready = fast.notna() & slow.notna()
        direction = empty_direction.copy()
        direction.loc[ready & (fast > slow)] = "long"
        direction.loc[ready & (fast < slow)] = "short"
        return _trend_entries(direction, spec.confirmation)

    if spec.family is StrategyFamily.DONCHIAN:
        assert spec.lookback is not None
        upper = candles["high"].shift(1).rolling(spec.lookback).max()
        lower = candles["low"].shift(1).rolling(spec.lookback).min()
        events = empty_direction.copy()
        events.loc[upper.notna() & (close > upper)] = "long"
        events.loc[lower.notna() & (close < lower)] = "short"
        direction = events.ffill()
        return _trend_entries(direction, spec.confirmation)

    if spec.family is StrategyFamily.MOMENTUM:
        assert spec.lookback is not None
        momentum = close / close.shift(spec.lookback) - 1
        events = empty_direction.copy()
        events.loc[momentum > spec.momentum_threshold] = "long"
        events.loc[momentum < -spec.momentum_threshold] = "short"
        direction = events.ffill()
        return _trend_entries(direction, spec.confirmation)

    rsi = RSIIndicator(close, window=spec.rsi_period).rsi()
    bands = BollingerBands(
        close,
        window=spec.bollinger_period,
        window_dev=spec.bollinger_deviation,
    )
    middle = bands.bollinger_mavg()
    lower = bands.bollinger_lband()
    upper = bands.bollinger_hband()
    ready = rsi.notna() & middle.notna() & lower.notna() & upper.notna()
    direction = empty_direction.copy()
    direction.loc[ready & (close < middle)] = "long"
    direction.loc[ready & (close > middle)] = "short"
    long_condition = ready & (close <= lower) & (rsi <= spec.rsi_lower)
    short_condition = ready & (close >= upper) & (rsi >= spec.rsi_upper)
    return (
        direction,
        _condition_run_reached(long_condition, spec.confirmation),
        _condition_run_reached(short_condition, spec.confirmation),
    )


def _trend_entries(
    direction: pd.Series,
    confirmation: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    return (
        direction,
        _run_reached(direction, "long", confirmation),
        _run_reached(direction, "short", confirmation),
    )


def _run_reached(direction: pd.Series, side: str, count: int) -> pd.Series:
    condition = direction.eq(side)
    return _condition_run_reached(condition, count)


def _condition_run_reached(condition: pd.Series, count: int) -> pd.Series:
    groups = condition.ne(condition.shift(fill_value=False)).cumsum()
    run_length = condition.groupby(groups).cumcount() + 1
    return condition & run_length.eq(count)


def _entry_permissions(
    candles: pd.DataFrame,
    spec: StrategySpec,
) -> dict[str, pd.Series]:
    index = candles.index
    long_allowed = pd.Series(True, index=index, dtype=bool)
    short_allowed = pd.Series(True, index=index, dtype=bool)
    close = candles["close"].astype(float)

    if spec.family is StrategyFamily.SAR and spec.ema_period is not None:
        ema = EMAIndicator(close, window=spec.ema_period).ema_indicator()
        long_allowed &= ema.notna() & close.gt(ema)
        short_allowed &= ema.notna() & close.lt(ema)

    if spec.adx_threshold is not None:
        if len(candles) >= spec.adx_period * 2:
            adx = ADXIndicator(
                high=candles["high"],
                low=candles["low"],
                close=close,
                window=spec.adx_period,
            ).adx()
            positions = pd.Series(np.arange(len(candles)), index=index)
            adx_ready = positions.ge(spec.adx_period * 2 - 1)
            allowed = adx_ready & adx.ge(spec.adx_threshold)
        else:
            allowed = pd.Series(False, index=index, dtype=bool)
        long_allowed &= allowed
        short_allowed &= allowed

    if spec.atr_min_percent is not None:
        if len(candles) >= spec.atr_period:
            atr = AverageTrueRange(
                high=candles["high"],
                low=candles["low"],
                close=close,
                window=spec.atr_period,
            ).average_true_range()
            positions = pd.Series(np.arange(len(candles)), index=index)
            allowed = positions.ge(spec.atr_period - 1) & (
                atr / close * 100 >= spec.atr_min_percent
            )
        else:
            allowed = pd.Series(False, index=index, dtype=bool)
        long_allowed &= allowed
        short_allowed &= allowed

    return {"long": long_allowed, "short": short_allowed}


def _permission_candles(
    series: CandleSeries,
    signal_candles: pd.DataFrame,
    spec: StrategySpec,
) -> pd.DataFrame:
    if spec.filter_timeframe is None or spec.filter_timeframe == spec.signal_timeframe:
        return signal_candles
    if spec.filter_timeframe == series.key.timeframe:
        return series.frame.loc[
            :, ["timestamp", "open", "high", "low", "close", "volume"]
        ].copy()
    return resample_ohlcv(
        series.frame,
        source_timeframe=series.key.timeframe,
        target_timeframe=spec.filter_timeframe,
    )


def _align_closed_filter(
    signal_candles: pd.DataFrame,
    filter_candles: pd.DataFrame,
    values: pd.Series,
    *,
    signal_timeframe: str,
    filter_timeframe: str | None,
) -> pd.Series:
    if filter_timeframe is None:
        raise StrategySignalError("filter timeframe is required for alignment")
    signal_closes = pd.DatetimeIndex(signal_candles["timestamp"]) + pd.Timedelta(
        milliseconds=_timeframe_ms(signal_timeframe)
    )
    filter_closes = pd.DatetimeIndex(filter_candles["timestamp"]) + pd.Timedelta(
        milliseconds=_timeframe_ms(filter_timeframe)
    )
    closed_values = pd.Series(values.to_numpy(dtype=bool), index=filter_closes)
    aligned = closed_values.reindex(signal_closes, method="ffill").eq(True)
    return pd.Series(aligned.to_numpy(dtype=bool), index=signal_candles.index)


def _timeframe_ms(timeframe: str) -> int:
    try:
        return int(timeframe_milliseconds(timeframe))
    except ValueError as exc:
        raise StrategySignalError(str(exc)) from exc


def _timestamp_ms(value: object) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)
