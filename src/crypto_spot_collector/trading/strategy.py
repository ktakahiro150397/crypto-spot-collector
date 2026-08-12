"""Closed-candle selection, deduplication and pure strategy transitions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterator, Protocol

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


class SarSignalChecker(Protocol):
    """The pure SAR checker operations shared by live and offline runtimes."""

    def get_current_sar_direction(self, df: pd.DataFrame) -> str | None: ...

    def check_long(self, df: pd.DataFrame, **kwargs: object) -> bool: ...

    def check_short(self, df: pd.DataFrame, **kwargs: object) -> bool: ...


@dataclass(frozen=True)
class SarSignalDecision:
    direction: str | None
    long_signal: bool
    short_signal: bool


def evaluate_sar_signal(
    frame: pd.DataFrame,
    checker: SarSignalChecker,
) -> SarSignalDecision:
    """Evaluate current direction and transition entry signals without I/O."""

    direction = checker.get_current_sar_direction(frame)
    if direction is None:
        return SarSignalDecision(None, False, False)
    return SarSignalDecision(
        direction=direction,
        long_signal=checker.check_long(frame),
        short_signal=checker.check_short(frame),
    )


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
    required_rows: int = 1,
) -> tuple[pd.DataFrame, CandleIdentity | None]:
    if required_rows <= 0:
        raise ValueError("required_rows must be greater than zero")
    if "timestamp" not in frame.columns:
        raise ValueError("candle frame requires a timestamp column")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise ValueError("candle timestamps contain invalid values")
    if timestamps.duplicated().any():
        raise ValueError("candle timestamps contain duplicates")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("candle timestamps must be strictly increasing")

    selected = closed_candles(frame, timeframe, now=now)
    if selected.empty:
        return selected, None
    if len(selected) < required_rows:
        raise ValueError("insufficient closed candles for indicator warm-up")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_ms = int(current.timestamp() * 1000)
    interval_ms = timeframe_milliseconds(timeframe)
    expected_latest_open_ms = (current_ms // interval_ms) * interval_ms - interval_ms
    selected_open_ms = (
        pd.to_datetime(selected["timestamp"], utc=True).astype("int64") // 1_000_000
    )
    if int(selected_open_ms.iloc[-1]) != expected_latest_open_ms:
        raise ValueError("latest closed candle slot is missing or stale")
    recent_open_ms = selected_open_ms.tail(required_rows).tolist()
    if any(
        current_open - previous_open != interval_ms
        for previous_open, current_open in zip(
            recent_open_ms, recent_open_ms[1:], strict=False
        )
    ):
        raise ValueError("recent closed candle sequence contains a gap")

    timestamp = pd.to_datetime(selected.iloc[-1]["timestamp"], utc=True)
    return selected, CandleIdentity(
        symbol, timeframe, int(timestamp.timestamp() * 1000)
    )


@dataclass(frozen=True)
class SarProgress:
    previous_direction: str | None
    current_direction: str
    opposite_count: int
    candle_open_ms: int


class SQLiteSarStateStore:
    """Persist per-candle SAR direction and opposite-position progress."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sar_progress (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candle_open_ms INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    opposite_count INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
                """
            )

    def advance(
        self,
        *,
        candle: CandleIdentity,
        direction: str,
        position_side: str | None,
    ) -> SarProgress | None:
        if direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if position_side not in {None, "long", "short"}:
            raise ValueError("position_side must be long, short, or None")

        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT candle_open_ms, direction, opposite_count
                FROM sar_progress WHERE symbol = ? AND timeframe = ?
                """,
                (candle.symbol, candle.timeframe),
            ).fetchone()
            if row is not None and candle.open_time_ms <= int(row["candle_open_ms"]):
                return None

            previous_direction = str(row["direction"]) if row is not None else None
            previous_count = int(row["opposite_count"]) if row is not None else 0
            is_opposite = position_side is not None and direction != position_side
            opposite_count = previous_count + 1 if is_opposite else 0
            connection.execute(
                """
                INSERT INTO sar_progress (
                    symbol, timeframe, candle_open_ms, direction, opposite_count
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    candle_open_ms = excluded.candle_open_ms,
                    direction = excluded.direction,
                    opposite_count = excluded.opposite_count
                """,
                (
                    candle.symbol,
                    candle.timeframe,
                    candle.open_time_ms,
                    direction,
                    opposite_count,
                ),
            )
        return SarProgress(
            previous_direction=previous_direction,
            current_direction=direction,
            opposite_count=opposite_count,
            candle_open_ms=candle.open_time_ms,
        )


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
