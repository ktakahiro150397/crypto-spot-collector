"""Closed-candle selection, deduplication and pure strategy transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import pandas as pd

from .config import timeframe_milliseconds


@dataclass(frozen=True, order=True)
class CandleIdentity:
    symbol: str
    timeframe: str
    open_time_ms: int


class CandleGate:
    """Accept each closed symbol/timeframe candle at most once per process."""

    def __init__(self) -> None:
        self._last_seen: dict[tuple[str, str], int] = {}

    def claim(self, candle: CandleIdentity) -> bool:
        key = (candle.symbol, candle.timeframe)
        last_seen = self._last_seen.get(key)
        if last_seen is not None and candle.open_time_ms <= last_seen:
            return False
        self._last_seen[key] = candle.open_time_ms
        return True


def closed_candles(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Return only candles whose entire interval has elapsed.

    The ``timestamp`` column is interpreted as the candle open time. Naive
    timestamps are treated as UTC because all repository records use UTC.
    """

    if frame.empty:
        return frame.copy()
    if "timestamp" not in frame.columns:
        raise ValueError("candle frame requires a timestamp column")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_ms = int(current.timestamp() * 1000)
    interval_ms = timeframe_milliseconds(timeframe)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    open_ms = timestamps.astype("int64") // 1_000_000
    mask = open_ms + interval_ms <= current_ms
    return frame.loc[mask].copy().reset_index(drop=True)


def latest_closed_identity(
    frame: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, CandleIdentity | None]:
    selected = closed_candles(frame, timeframe, now=now)
    if selected.empty:
        return selected, None
    timestamp = pd.to_datetime(selected.iloc[-1]["timestamp"], utc=True)
    return selected, CandleIdentity(symbol, timeframe, int(timestamp.timestamp() * 1000))


class StrategyState(str, Enum):
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"
    CLOSING_LONG = "closing_long"
    CLOSING_SHORT = "closing_short"


class StrategyAction(str, Enum):
    HOLD = "hold"
    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


class StrategyStateMachine:
    """Explicit two-phase close/reverse strategy state.

    An opposite signal first produces a close action and records the pending
    side. The reverse entry can only be emitted by ``confirm_flat`` after the
    exchange has confirmed that the prior position is zero.
    """

    def __init__(self, state: StrategyState = StrategyState.FLAT) -> None:
        self.state = state
        self.pending_side: StrategyState | None = None

    def on_signal(self, side: StrategyState | None) -> StrategyAction:
        if side not in {None, StrategyState.LONG, StrategyState.SHORT}:
            raise ValueError(f"invalid signal side: {side}")
        if side is None:
            return StrategyAction.HOLD
        if self.state is StrategyState.FLAT:
            self.state = side
            return (
                StrategyAction.OPEN_LONG
                if side is StrategyState.LONG
                else StrategyAction.OPEN_SHORT
            )
        if self.state is side:
            return StrategyAction.HOLD
        if self.state is StrategyState.LONG:
            self.pending_side = StrategyState.SHORT
            self.state = StrategyState.CLOSING_LONG
            return StrategyAction.CLOSE_LONG
        if self.state is StrategyState.SHORT:
            self.pending_side = StrategyState.LONG
            self.state = StrategyState.CLOSING_SHORT
            return StrategyAction.CLOSE_SHORT
        return StrategyAction.HOLD

    def confirm_flat(self) -> StrategyAction:
        if self.state not in {StrategyState.CLOSING_LONG, StrategyState.CLOSING_SHORT}:
            raise RuntimeError("flat confirmation is only valid while closing")
        pending = self.pending_side
        self.pending_side = None
        self.state = StrategyState.FLAT
        if pending is StrategyState.LONG:
            self.state = StrategyState.LONG
            return StrategyAction.OPEN_LONG
        if pending is StrategyState.SHORT:
            self.state = StrategyState.SHORT
            return StrategyAction.OPEN_SHORT
        return StrategyAction.HOLD
