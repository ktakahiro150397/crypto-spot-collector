"""Causal portfolio targets and fail-closed rebalance planning.

This module deliberately has no exchange client dependency.  It turns completed
daily candles into an auditable target, persists that target, and produces one
safe execution phase at a time.  The caller must reconcile every phase against
exchange positions before asking for the next plan.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterator, Mapping

import numpy as np
import pandas as pd

DAY_MS = 86_400_000
STRATEGY_NAME = "daily_trend_ensemble_v1"
SELECTED_PORTFOLIO_SYMBOLS = (
    "BTC/USDC:USDC",
    "ETH/USDC:USDC",
    "SOL/USDC:USDC",
    "XRP/USDC:USDC",
    "BNB/USDC:USDC",
    "DOGE/USDC:USDC",
)


@dataclass(frozen=True)
class TrendEnsembleConfig:
    """Frozen parameters selected by the portfolio backtest."""

    symbols: tuple[str, ...]
    gross_notional_usdc: float = 75.0
    momentum_days: int = 28
    ema_days: int = 56
    donchian_days: int = 28
    volatility_days: int = 7
    daily_volatility_target: float = 0.04
    minimum_volatility_scale: float = 0.25
    maximum_volatility_scale: float = 1.0
    vote_threshold: int = 2
    max_order_notional_usdc: float = 75.0
    max_symbol_notional_usdc: float = 75.0
    max_positions: int = 6
    rebalance_tolerance_usdc: float = 0.25
    max_decision_delay_seconds: int = 21_600

    def __post_init__(self) -> None:
        normalized = tuple(symbol.strip().upper() for symbol in self.symbols)
        object.__setattr__(self, "symbols", normalized)
        if (
            len(normalized) < 2
            or len(set(normalized)) != len(normalized)
            or any(not symbol for symbol in normalized)
        ):
            raise ValueError("symbols must contain at least two unique values")
        positive_finite = {
            "gross_notional_usdc": self.gross_notional_usdc,
            "daily_volatility_target": self.daily_volatility_target,
            "minimum_volatility_scale": self.minimum_volatility_scale,
            "maximum_volatility_scale": self.maximum_volatility_scale,
            "max_order_notional_usdc": self.max_order_notional_usdc,
            "max_symbol_notional_usdc": self.max_symbol_notional_usdc,
        }
        for name, value in positive_finite.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        for name in (
            "momentum_days",
            "ema_days",
            "donchian_days",
            "volatility_days",
            "vote_threshold",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.vote_threshold > 3:
            raise ValueError("vote_threshold cannot exceed the three indicators")
        if self.minimum_volatility_scale > self.maximum_volatility_scale:
            raise ValueError("minimum volatility scale exceeds maximum")
        if self.maximum_volatility_scale > 1:
            raise ValueError("maximum volatility scale cannot lever above the cap")
        if self.max_symbol_notional_usdc > self.gross_notional_usdc:
            raise ValueError("symbol notional limit cannot exceed gross limit")
        if self.max_order_notional_usdc > self.max_symbol_notional_usdc:
            raise ValueError("order notional limit cannot exceed symbol limit")
        if not 1 <= self.max_positions <= len(normalized):
            raise ValueError("max_positions must fit the symbol allowlist")
        if self.max_decision_delay_seconds <= 0:
            raise ValueError("max_decision_delay_seconds must be positive")
        if (
            not math.isfinite(self.rebalance_tolerance_usdc)
            or self.rebalance_tolerance_usdc < 0
        ):
            raise ValueError("rebalance tolerance must be finite and non-negative")

    @property
    def required_rows(self) -> int:
        return max(
            self.momentum_days + 1,
            self.ema_days,
            self.donchian_days + 1,
            self.volatility_days + 1,
        )


@dataclass(frozen=True)
class PortfolioTarget:
    symbol: str
    momentum_direction: int
    ema_direction: int
    donchian_direction: int
    votes: int
    daily_volatility: float
    weight: float
    signed_notional_usdc: float


@dataclass(frozen=True)
class PortfolioDecision:
    decision_id: str
    strategy: str
    candle_close_ms: int
    observed_at_ms: int
    gross_notional_usdc: float
    targets: tuple[PortfolioTarget, ...]

    @property
    def target_notionals(self) -> dict[str, float]:
        return {target.symbol: target.signed_notional_usdc for target in self.targets}


class RebalancePhase(StrEnum):
    REDUCE = "reduce"
    INCREASE = "increase"
    COMPLETE = "complete"


@dataclass(frozen=True)
class RebalanceAction:
    symbol: str
    side: str
    notional_usdc: float
    reduce_only: bool


@dataclass(frozen=True)
class RebalancePlan:
    plan_id: str
    decision_id: str
    position_snapshot_id: str
    phase: RebalancePhase
    actions: tuple[RebalanceAction, ...]
    requires_position_refresh: bool


class DecisionStatus(StrEnum):
    PREPARED = "prepared"
    REDUCING = "reducing"
    INCREASING = "increasing"
    COMPLETE = "complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class StoredPortfolioDecision:
    decision: PortfolioDecision
    status: DecisionStatus


_ALLOWED_STATUS_TRANSITIONS = {
    DecisionStatus.PREPARED: {
        DecisionStatus.REDUCING,
        DecisionStatus.INCREASING,
        DecisionStatus.COMPLETE,
        DecisionStatus.BLOCKED,
    },
    DecisionStatus.REDUCING: {
        DecisionStatus.INCREASING,
        DecisionStatus.COMPLETE,
        DecisionStatus.BLOCKED,
    },
    DecisionStatus.INCREASING: {
        DecisionStatus.REDUCING,
        DecisionStatus.COMPLETE,
        DecisionStatus.BLOCKED,
    },
    DecisionStatus.BLOCKED: set(),
    DecisionStatus.COMPLETE: set(),
}


def calculate_trend_ensemble_target(
    *,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    observed_at_ms: int,
    config: TrendEnsembleConfig,
) -> PortfolioDecision:
    """Calculate a target from aligned, completed UTC daily candles only."""

    _validate_market_frames(highs, lows, closes, observed_at_ms, config)
    closes = closes.loc[:, list(config.symbols)].astype(float)
    highs = highs.loc[:, list(config.symbols)].astype(float)
    lows = lows.loc[:, list(config.symbols)].astype(float)

    momentum = _sign(closes / closes.shift(config.momentum_days) - 1)
    ema = closes.ewm(
        span=config.ema_days,
        adjust=False,
        min_periods=config.ema_days,
    ).mean()
    ema_direction = _sign(closes - ema)
    upper = highs.shift(1).rolling(config.donchian_days).max()
    lower = lows.shift(1).rolling(config.donchian_days).min()
    donchian_events = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
    donchian_events = donchian_events.mask(closes.gt(upper), 1.0)
    donchian_events = donchian_events.mask(closes.lt(lower), -1.0)
    donchian = donchian_events.ffill().fillna(0.0)

    votes = momentum + ema_direction + donchian
    signal = pd.DataFrame(
        np.select(
            [votes >= config.vote_threshold, votes <= -config.vote_threshold],
            [1.0, -1.0],
            default=0.0,
        ),
        index=closes.index,
        columns=closes.columns,
    )
    daily_volatility = closes.pct_change().rolling(config.volatility_days).std()
    inverse_volatility = 1 / daily_volatility.replace(0, np.nan)
    raw_weight = signal * inverse_volatility.clip(upper=1_000)
    gross = raw_weight.abs().sum(axis=1).replace(0, np.nan)
    weight = raw_weight.div(gross, axis=0).fillna(0.0)
    approximate_volatility = ((weight * daily_volatility) ** 2).sum(axis=1).pow(0.5)
    scale = (
        config.daily_volatility_target / approximate_volatility.replace(0, np.nan)
    ).clip(
        lower=config.minimum_volatility_scale,
        upper=config.maximum_volatility_scale,
    )
    weight = weight.mul(scale.fillna(0.0), axis=0)

    last = -1
    targets = tuple(
        PortfolioTarget(
            symbol=symbol,
            momentum_direction=int(momentum.iloc[last][symbol]),
            ema_direction=int(ema_direction.iloc[last][symbol]),
            donchian_direction=int(donchian.iloc[last][symbol]),
            votes=int(votes.iloc[last][symbol]),
            daily_volatility=float(daily_volatility.iloc[last][symbol]),
            weight=_clean_zero(float(weight.iloc[last][symbol])),
            signed_notional_usdc=_clean_zero(
                float(weight.iloc[last][symbol]) * config.gross_notional_usdc
            ),
        )
        for symbol in config.symbols
    )
    _validate_targets(targets, config)
    last_open_ms = int(pd.Timestamp(closes.index[-1]).timestamp() * 1_000)
    candle_close_ms = last_open_ms + DAY_MS
    payload = {
        "strategy": STRATEGY_NAME,
        "candle_close_ms": candle_close_ms,
        "gross_notional_usdc": config.gross_notional_usdc,
        "targets": [asdict(target) for target in targets],
    }
    decision_id = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
    return PortfolioDecision(
        decision_id=decision_id,
        strategy=STRATEGY_NAME,
        candle_close_ms=candle_close_ms,
        observed_at_ms=observed_at_ms,
        gross_notional_usdc=config.gross_notional_usdc,
        targets=targets,
    )


def plan_rebalance(
    decision: PortfolioDecision,
    positions: Mapping[str, float],
    config: TrendEnsembleConfig,
) -> RebalancePlan:
    """Return reductions or increases, never both in one execution phase.

    Position values and target values are signed notionals: positive is long,
    negative is short.  After any returned action the caller must fetch exchange
    positions again and call this function with the refreshed snapshot.
    """

    targets = decision.target_notionals
    if set(targets) != set(config.symbols):
        raise ValueError("decision symbols do not match the configured allowlist")
    normalized_positions = {
        symbol.upper(): value for symbol, value in positions.items()
    }
    if len(normalized_positions) != len(positions):
        raise ValueError("position snapshot contains duplicate normalized symbols")
    unknown = set(normalized_positions) - set(config.symbols)
    if unknown:
        raise ValueError(
            f"position snapshot contains unknown symbols: {sorted(unknown)}"
        )
    current = {
        symbol: float(normalized_positions.get(symbol, 0.0))
        for symbol in config.symbols
    }
    for symbol, value in current.items():
        if not math.isfinite(value):
            raise ValueError(f"position notional for {symbol} is not finite")
    _validate_decision_limits(decision, config)

    reductions: list[RebalanceAction] = []
    current_gross = sum(abs(value) for value in current.values())
    portfolio_is_over_limit = current_gross > config.gross_notional_usdc + 1e-9
    for symbol in config.symbols:
        live = current[symbol]
        target = targets[symbol]
        if live == 0:
            continue
        same_side = live * target > 0
        if not same_side:
            reduction = abs(live)
        elif (
            abs(live) > config.max_symbol_notional_usdc + 1e-9
            or portfolio_is_over_limit
        ) and abs(live) > abs(target) + 1e-9:
            reduction = abs(live) - abs(target)
        elif abs(live) > abs(target) + config.rebalance_tolerance_usdc:
            reduction = abs(live) - abs(target)
        else:
            continue
        reductions.append(
            RebalanceAction(
                symbol=symbol,
                side="sell" if live > 0 else "buy",
                notional_usdc=min(reduction, config.max_order_notional_usdc),
                reduce_only=True,
            )
        )
    snapshot_id = _position_snapshot_id(current)
    if reductions:
        return _build_plan(
            decision,
            snapshot_id,
            RebalancePhase.REDUCE,
            reductions,
            requires_position_refresh=True,
        )

    increases: list[RebalanceAction] = []
    for symbol in config.symbols:
        live = current[symbol]
        target = targets[symbol]
        difference = target - live
        if abs(difference) <= config.rebalance_tolerance_usdc:
            continue
        if live * target < 0:
            raise RuntimeError("reversal remained after the reduction phase")
        increases.append(
            RebalanceAction(
                symbol=symbol,
                side="buy" if difference > 0 else "sell",
                notional_usdc=min(abs(difference), config.max_order_notional_usdc),
                reduce_only=False,
            )
        )
    if increases:
        return _build_plan(
            decision,
            snapshot_id,
            RebalancePhase.INCREASE,
            increases,
            requires_position_refresh=True,
        )
    return _build_plan(
        decision,
        snapshot_id,
        RebalancePhase.COMPLETE,
        [],
        requires_position_refresh=False,
    )


class SQLitePortfolioDecisionStore:
    """Durable target state used to resume a rebalance without recomputation."""

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
            health = connection.execute("PRAGMA quick_check").fetchone()
            if health is None or health[0] != "ok":
                raise sqlite3.DatabaseError(
                    "portfolio decision database quick_check failed"
                )
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_decisions (
                    decision_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    candle_close_ms INTEGER NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def prepare(
        self, decision: PortfolioDecision
    ) -> tuple[StoredPortfolioDecision, bool]:
        payload = _serialize_decision(decision)
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            same_candle = connection.execute(
                "SELECT * FROM portfolio_decisions WHERE candle_close_ms = ?",
                (decision.candle_close_ms,),
            ).fetchone()
            if same_candle is not None:
                stored = self._from_row(same_candle)
                if same_candle["payload"] != payload:
                    raise ValueError("conflicting target for an existing candle")
                return stored, False
            active = connection.execute(
                """
                SELECT * FROM portfolio_decisions
                WHERE status NOT IN (?, ?)
                ORDER BY candle_close_ms DESC LIMIT 1
                """,
                (DecisionStatus.COMPLETE.value, DecisionStatus.BLOCKED.value),
            ).fetchone()
            if active is not None:
                raise RuntimeError(
                    "an earlier portfolio decision must be completed or blocked first"
                )
            connection.execute(
                """
                INSERT INTO portfolio_decisions (
                    decision_id, strategy, candle_close_ms, payload, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.strategy,
                    decision.candle_close_ms,
                    payload,
                    DecisionStatus.PREPARED.value,
                    _now(),
                ),
            )
        return StoredPortfolioDecision(decision, DecisionStatus.PREPARED), True

    def latest(self) -> StoredPortfolioDecision | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_decisions ORDER BY candle_close_ms DESC LIMIT 1"
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def transition(
        self, decision_id: str, status: DecisionStatus
    ) -> StoredPortfolioDecision:
        with self._transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM portfolio_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if row is None:
                raise KeyError(decision_id)
            current = DecisionStatus(row["status"])
            if (
                status is not current
                and status not in _ALLOWED_STATUS_TRANSITIONS[current]
            ):
                raise ValueError(
                    f"invalid portfolio decision transition: {current} -> {status}"
                )
            connection.execute(
                "UPDATE portfolio_decisions SET status = ?, updated_at = ? WHERE decision_id = ?",
                (status.value, _now(), decision_id),
            )
            updated = connection.execute(
                "SELECT * FROM portfolio_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        assert updated is not None
        return self._from_row(updated)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredPortfolioDecision:
        return StoredPortfolioDecision(
            decision=_deserialize_decision(row["payload"]),
            status=DecisionStatus(row["status"]),
        )


def _validate_market_frames(
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    observed_at_ms: int,
    config: TrendEnsembleConfig,
) -> None:
    if isinstance(observed_at_ms, bool) or not isinstance(observed_at_ms, int):
        raise ValueError("observed_at_ms must be an integer")
    frames = (highs, lows, closes)
    if any(frame.empty for frame in frames):
        raise ValueError("market frames must not be empty")
    if any(not frame.index.equals(closes.index) for frame in frames[:-1]):
        raise ValueError("market timestamps do not align")
    if any(set(frame.columns) != set(config.symbols) for frame in frames):
        raise ValueError("market symbols must exactly match the allowlist")
    if len(closes) < config.required_rows:
        raise ValueError(f"at least {config.required_rows} daily candles are required")
    if not isinstance(closes.index, pd.DatetimeIndex):
        raise ValueError("market index must be a DatetimeIndex")
    if closes.index.tz is None or str(closes.index.tz) != "UTC":
        raise ValueError("market timestamps must be timezone-aware UTC")
    if not closes.index.is_monotonic_increasing or not closes.index.is_unique:
        raise ValueError("market timestamps must be unique and increasing")
    if any(
        timestamp.hour or timestamp.minute or timestamp.second or timestamp.microsecond
        for timestamp in closes.index
    ):
        raise ValueError("daily candles must open at 00:00 UTC")
    intervals = closes.index.to_series().diff().dropna()
    if not intervals.eq(pd.Timedelta(days=1)).all():
        raise ValueError("market data must be contiguous daily candles")
    final_close_ms = int(pd.Timestamp(closes.index[-1]).timestamp() * 1_000) + DAY_MS
    if observed_at_ms < final_close_ms:
        raise ValueError("the final candle is not complete at observed_at_ms")
    maximum_delay_ms = config.max_decision_delay_seconds * 1_000
    if observed_at_ms - final_close_ms > maximum_delay_ms:
        raise ValueError("the final completed candle is stale")
    values = [
        frame.loc[:, list(config.symbols)].to_numpy(dtype=float) for frame in frames
    ]
    if any(not np.isfinite(value).all() or (value <= 0).any() for value in values):
        raise ValueError("market prices must be finite and positive")
    high_values, low_values, close_values = values
    if (high_values < low_values).any():
        raise ValueError("market high is below low")
    if (close_values > high_values).any() or (close_values < low_values).any():
        raise ValueError("market close is outside the high-low range")


def _validate_targets(
    targets: tuple[PortfolioTarget, ...], config: TrendEnsembleConfig
) -> None:
    if any(
        not math.isfinite(target.daily_volatility)
        or not math.isfinite(target.weight)
        or not math.isfinite(target.signed_notional_usdc)
        for target in targets
    ):
        raise ValueError("indicator warm-up did not produce finite targets")
    gross = sum(abs(target.signed_notional_usdc) for target in targets)
    if gross > config.gross_notional_usdc + 1e-9:
        raise ValueError("calculated target exceeds the portfolio gross cap")
    if any(
        abs(target.signed_notional_usdc) > config.max_symbol_notional_usdc + 1e-9
        for target in targets
    ):
        raise ValueError("calculated target exceeds a symbol notional limit")
    active = sum(target.signed_notional_usdc != 0 for target in targets)
    if active > config.max_positions:
        raise ValueError("calculated target exceeds max_positions")


def _validate_decision_limits(
    decision: PortfolioDecision, config: TrendEnsembleConfig
) -> None:
    if decision.strategy != STRATEGY_NAME:
        raise ValueError("decision strategy is not the configured portfolio strategy")
    if tuple(target.symbol for target in decision.targets) != config.symbols:
        raise ValueError("decision target order does not exactly match the allowlist")
    gross = sum(abs(value) for value in decision.target_notionals.values())
    if not math.isfinite(gross) or gross > config.gross_notional_usdc + 1e-9:
        raise ValueError("decision exceeds the configured gross notional limit")
    if not math.isclose(
        decision.gross_notional_usdc,
        config.gross_notional_usdc,
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise ValueError("decision gross cap differs from runtime configuration")
    _validate_targets(decision.targets, config)


def _build_plan(
    decision: PortfolioDecision,
    snapshot_id: str,
    phase: RebalancePhase,
    actions: list[RebalanceAction],
    *,
    requires_position_refresh: bool,
) -> RebalancePlan:
    payload = {
        "decision_id": decision.decision_id,
        "position_snapshot_id": snapshot_id,
        "phase": phase.value,
        "actions": [asdict(action) for action in actions],
    }
    return RebalancePlan(
        plan_id=hashlib.sha256(_canonical_json(payload).encode()).hexdigest(),
        decision_id=decision.decision_id,
        position_snapshot_id=snapshot_id,
        phase=phase,
        actions=tuple(actions),
        requires_position_refresh=requires_position_refresh,
    )


def _position_snapshot_id(positions: Mapping[str, float]) -> str:
    normalized = {symbol: float(f"{value:.12g}") for symbol, value in positions.items()}
    return hashlib.sha256(_canonical_json(normalized).encode()).hexdigest()


def _serialize_decision(decision: PortfolioDecision) -> str:
    return _canonical_json(
        {
            **asdict(decision),
            "targets": [asdict(target) for target in decision.targets],
        }
    )


def _deserialize_decision(payload: str) -> PortfolioDecision:
    data = json.loads(payload)
    data["targets"] = tuple(PortfolioTarget(**target) for target in data["targets"])
    return PortfolioDecision(**data)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sign(values: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        np.sign(values.to_numpy(dtype=float)),
        index=values.index,
        columns=values.columns,
    ).fillna(0.0)


def _clean_zero(value: float) -> float:
    return 0.0 if abs(value) < 1e-12 else value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
