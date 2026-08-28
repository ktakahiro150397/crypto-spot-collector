"""Cross-asset portfolio arsenal with causal walk-forward evaluation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast

import numpy as np
import pandas as pd

from crypto_spot_collector.trading.config import timeframe_milliseconds


class PortfolioFamily(StrEnum):
    TIME_SERIES_MOMENTUM = "time_series_momentum"
    TIME_SERIES_REVERSAL = "time_series_reversal"
    CROSS_SECTION_MOMENTUM = "cross_section_momentum"
    CROSS_SECTION_REVERSAL = "cross_section_reversal"
    EMA_TREND = "ema_trend"
    DONCHIAN_BREAKOUT = "donchian_breakout"
    TREND_ENSEMBLE = "trend_ensemble"


class PortfolioSide(StrEnum):
    BOTH = "both"
    LONG_ONLY = "long_only"


@dataclass(frozen=True)
class PortfolioSpec:
    family: PortfolioFamily
    timeframe: str
    lookback_days: float
    side: PortfolioSide = PortfolioSide.BOTH
    top_k: int = 1
    absolute_gate: bool = False
    volatility_managed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", PortfolioFamily(str(self.family)))
        object.__setattr__(self, "side", PortfolioSide(str(self.side)))
        object.__setattr__(self, "timeframe", self.timeframe.lower())
        if self.lookback_days <= 0 or not math.isfinite(self.lookback_days):
            raise ValueError("lookback_days must be finite and positive")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        bars = self.lookback_days * bars_per_day(self.timeframe)
        if not math.isclose(bars, round(bars)):
            raise ValueError("lookback_days must resolve to a whole candle count")

    @property
    def identifier(self) -> str:
        return (
            f"{self.family.value}|tf={self.timeframe}|days={self.lookback_days:g}|"
            f"side={self.side.value}|top={self.top_k}|"
            f"gate={int(self.absolute_gate)}|vol={int(self.volatility_managed)}"
        )

    @property
    def neighborhood(self) -> str:
        return (
            f"{self.family.value}|tf={self.timeframe}|side={self.side.value}|"
            f"top={self.top_k}|gate={int(self.absolute_gate)}|"
            f"vol={int(self.volatility_managed)}"
        )

    @property
    def lookback_bars(self) -> int:
        return int(round(self.lookback_days * bars_per_day(self.timeframe)))

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["family"] = self.family.value
        values["side"] = self.side.value
        return values


@dataclass(frozen=True)
class PortfolioMarket:
    timeframe: str
    opens: pd.DataFrame
    highs: pd.DataFrame
    lows: pd.DataFrame
    closes: pd.DataFrame

    def validate(self) -> None:
        frames = (self.opens, self.highs, self.lows, self.closes)
        if any(frame.empty for frame in frames):
            raise ValueError("portfolio market frames must not be empty")
        if any(not frame.index.equals(self.opens.index) for frame in frames[1:]):
            raise ValueError("portfolio market timestamps do not align")
        if any(not frame.columns.equals(self.opens.columns) for frame in frames[1:]):
            raise ValueError("portfolio market symbols do not align")
        if len(self.opens.columns) < 2:
            raise ValueError("portfolio evaluation requires at least two symbols")
        if self.opens.isna().any().any() or self.closes.isna().any().any():
            raise ValueError("portfolio market contains missing prices")


@dataclass(frozen=True)
class PortfolioCosts:
    initial_equity: float = 1_000.0
    gross_notional: float = 75.0
    taker_fee_bps: float = 4.322
    slippage_bps: float = 1.0
    adverse_funding_bps: float = 1.0
    funding_interval_hours: int = 8

    @property
    def transaction_rate(self) -> float:
        return (self.taker_fee_bps + self.slippage_bps) / 10_000


def bars_per_day(timeframe: str) -> float:
    interval = timeframe_milliseconds(timeframe)
    return float(86_400_000 / interval)


def build_portfolio_grid() -> list[PortfolioSpec]:
    """Return the pre-registered portfolio search grid."""

    specs: set[PortfolioSpec] = set()
    trend_timeframes = ("4h", "12h", "1d")
    sides = (PortfolioSide.BOTH, PortfolioSide.LONG_ONLY)
    volatility_modes = (False, True)

    for timeframe in trend_timeframes:
        for days in (3.0, 7.0, 14.0, 28.0):
            for side in sides:
                for volatility_managed in volatility_modes:
                    specs.add(
                        PortfolioSpec(
                            PortfolioFamily.TIME_SERIES_MOMENTUM,
                            timeframe,
                            days,
                            side,
                            volatility_managed=volatility_managed,
                        )
                    )
            for side in sides:
                for top_k in (1, 2):
                    for absolute_gate in (False, True):
                        for volatility_managed in volatility_modes:
                            specs.add(
                                PortfolioSpec(
                                    PortfolioFamily.CROSS_SECTION_MOMENTUM,
                                    timeframe,
                                    days,
                                    side,
                                    top_k,
                                    absolute_gate,
                                    volatility_managed,
                                )
                            )
            for family in (
                PortfolioFamily.DONCHIAN_BREAKOUT,
                PortfolioFamily.TREND_ENSEMBLE,
            ):
                for side in sides:
                    for volatility_managed in volatility_modes:
                        specs.add(
                            PortfolioSpec(
                                family,
                                timeframe,
                                days,
                                side,
                                volatility_managed=volatility_managed,
                            )
                        )
        for days in (7.0, 14.0, 28.0, 56.0):
            for side in sides:
                for volatility_managed in volatility_modes:
                    specs.add(
                        PortfolioSpec(
                            PortfolioFamily.EMA_TREND,
                            timeframe,
                            days,
                            side,
                            volatility_managed=volatility_managed,
                        )
                    )

    for timeframe in ("4h", "12h"):
        for days in (0.5, 1.0, 3.0):
            for side in sides:
                for volatility_managed in volatility_modes:
                    specs.add(
                        PortfolioSpec(
                            PortfolioFamily.TIME_SERIES_REVERSAL,
                            timeframe,
                            days,
                            side,
                            volatility_managed=volatility_managed,
                        )
                    )
            for top_k in (1, 2):
                for volatility_managed in volatility_modes:
                    specs.add(
                        PortfolioSpec(
                            PortfolioFamily.CROSS_SECTION_REVERSAL,
                            timeframe,
                            days,
                            PortfolioSide.BOTH,
                            top_k,
                            volatility_managed=volatility_managed,
                        )
                    )
    return sorted(specs, key=lambda spec: spec.identifier)


def prepare_weights(market: PortfolioMarket, spec: PortfolioSpec) -> pd.DataFrame:
    """Create close-time target weights without looking into the next candle."""

    market.validate()
    if market.timeframe != spec.timeframe:
        raise ValueError("market timeframe does not match portfolio specification")
    lookback = spec.lookback_bars
    close = market.closes
    past_return = close / close.shift(lookback) - 1
    family = spec.family

    if family is PortfolioFamily.TIME_SERIES_MOMENTUM:
        signal = _sign(past_return)
    elif family is PortfolioFamily.TIME_SERIES_REVERSAL:
        signal = -_sign(past_return)
    elif family is PortfolioFamily.CROSS_SECTION_MOMENTUM:
        signal = _cross_section_signal(
            past_return,
            top_k=spec.top_k,
            reversal=False,
            side=spec.side,
            absolute_gate=spec.absolute_gate,
        )
    elif family is PortfolioFamily.CROSS_SECTION_REVERSAL:
        signal = _cross_section_signal(
            past_return,
            top_k=spec.top_k,
            reversal=True,
            side=spec.side,
            absolute_gate=False,
        )
    elif family is PortfolioFamily.EMA_TREND:
        ema = close.ewm(span=lookback, adjust=False, min_periods=lookback).mean()
        signal = _sign(close - ema)
    elif family is PortfolioFamily.DONCHIAN_BREAKOUT:
        signal = _donchian_direction(market, lookback)
    else:
        momentum = _sign(past_return)
        ema = close.ewm(
            span=lookback * 2,
            adjust=False,
            min_periods=lookback * 2,
        ).mean()
        ema_direction = _sign(close - ema)
        donchian = _donchian_direction(market, lookback)
        votes = momentum + ema_direction + donchian
        signal = pd.DataFrame(
            np.select([votes >= 2, votes <= -2], [1.0, -1.0], default=0.0),
            index=close.index,
            columns=close.columns,
        )

    if spec.side is PortfolioSide.LONG_ONLY:
        signal = signal.clip(lower=0)
    returns = close.pct_change()
    if spec.volatility_managed:
        vol_window = max(6, int(round(7 * bars_per_day(spec.timeframe))))
        daily_vol = returns.rolling(vol_window).std() * math.sqrt(
            bars_per_day(spec.timeframe)
        )
        inverse_vol = (1 / daily_vol.replace(0, np.nan)).clip(upper=1_000)
        raw_weights = signal * inverse_vol
    else:
        daily_vol = None
        raw_weights = signal
    gross = raw_weights.abs().sum(axis=1).replace(0, np.nan)
    weights = raw_weights.div(gross, axis=0).fillna(0.0)

    if daily_vol is not None:
        approximate_vol = ((weights * daily_vol) ** 2).sum(axis=1).pow(0.5)
        scale = (0.04 / approximate_vol.replace(0, np.nan)).clip(
            lower=0.25,
            upper=1.0,
        )
        weights = weights.mul(scale.fillna(0.0), axis=0)
    return weights


def evaluate_portfolio(
    market: PortfolioMarket,
    spec: PortfolioSpec,
    costs: PortfolioCosts = PortfolioCosts(),
) -> dict[str, Any]:
    """Replay next-open execution and flat liquidation at the fold end."""

    weights = prepare_weights(market, spec).shift(1).fillna(0.0)
    opens = market.opens
    interval_ms = timeframe_milliseconds(spec.timeframe)
    interval = pd.Timedelta(milliseconds=interval_ms)
    rows: list[dict[str, Any]] = []
    previous = pd.Series(0.0, index=opens.columns)
    equity = costs.initial_equity
    stressed_equity = costs.initial_equity
    peak = equity
    max_drawdown = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    total_cost = 0.0
    total_funding = 0.0
    total_turnover = 0.0
    rebalance_count = 0
    position_change_count = 0
    symbol_gross_pnl = pd.Series(0.0, index=opens.columns)
    symbol_transaction_cost = pd.Series(0.0, index=opens.columns)
    symbol_funding_cost = pd.Series(0.0, index=opens.columns)

    for index in range(len(opens)):
        timestamp = pd.Timestamp(opens.index[index])
        target = weights.iloc[index]
        weight_change = (target - previous).abs()
        turnover = float(weight_change.sum())
        transaction_by_symbol = (
            costs.gross_notional * weight_change * costs.transaction_rate
        )
        transaction_cost = float(transaction_by_symbol.sum())
        if turnover > 1e-12:
            rebalance_count += 1
        position_change_count += int(
            (
                (_sign_series(target) != _sign_series(previous)) & (target != previous)
            ).sum()
        )
        total_turnover += turnover
        total_cost += transaction_cost

        if index + 1 < len(opens):
            end = pd.Timestamp(opens.index[index + 1])
            interval_return = opens.iloc[index + 1] / opens.iloc[index] - 1
        else:
            end = timestamp + interval
            interval_return = market.closes.iloc[index] / opens.iloc[index] - 1
        gross_by_symbol = costs.gross_notional * target * interval_return
        gross_pnl = float(gross_by_symbol.sum())
        funding_events = _funding_events(
            timestamp,
            end,
            interval_hours=costs.funding_interval_hours,
        )
        funding_by_symbol = (
            costs.gross_notional
            * target.abs()
            * costs.adverse_funding_bps
            / 10_000
            * funding_events
        )
        funding_cost = float(funding_by_symbol.sum())
        net_pnl = gross_pnl - transaction_cost
        stressed_pnl = net_pnl - funding_cost
        equity += net_pnl
        stressed_equity += stressed_pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity - peak) / peak)
        if net_pnl > 0:
            gross_profit += net_pnl
        elif net_pnl < 0:
            gross_loss += net_pnl
        total_funding += funding_cost
        symbol_gross_pnl += gross_by_symbol
        symbol_transaction_cost += transaction_by_symbol
        symbol_funding_cost += funding_by_symbol
        rows.append(
            {
                "timestamp": end.isoformat(),
                "equity": equity,
                "stressed_equity": stressed_equity,
                "net_pnl": net_pnl,
            }
        )
        previous = target

    liquidation_by_symbol = (
        costs.gross_notional * previous.abs() * costs.transaction_rate
    )
    liquidation_cost = float(liquidation_by_symbol.sum())
    equity -= liquidation_cost
    stressed_equity -= liquidation_cost
    total_cost += liquidation_cost
    symbol_transaction_cost += liquidation_by_symbol
    total_turnover += float(previous.abs().sum())
    if liquidation_cost > 0:
        rebalance_count += 1
        position_change_count += int(previous.ne(0).sum())
        gross_loss -= liquidation_cost
    peak = max(peak, equity)
    max_drawdown = min(max_drawdown, (equity - peak) / peak)
    if rows:
        rows[-1]["equity"] = equity
        rows[-1]["stressed_equity"] = stressed_equity
        rows[-1]["net_pnl"] = float(rows[-1]["net_pnl"]) - liquidation_cost

    interval_pnl = pd.Series([float(row["net_pnl"]) for row in rows])
    pnl_std = float(interval_pnl.std(ddof=1)) if len(interval_pnl) > 1 else 0.0
    annualization = math.sqrt(365 * bars_per_day(spec.timeframe))
    sharpe = (
        float(interval_pnl.mean()) / pnl_std * annualization if pnl_std > 0 else 0.0
    )
    return {
        "candidate": spec.identifier,
        "neighborhood": spec.neighborhood,
        **spec.as_dict(),
        "net_pnl": equity - costs.initial_equity,
        "stressed_net_pnl": stressed_equity - costs.initial_equity,
        "double_cost_net_pnl": equity - costs.initial_equity - total_cost,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / abs(gross_loss) if gross_loss < 0 else None),
        "max_drawdown_percent": abs(max_drawdown) * 100,
        "sharpe": sharpe,
        "transaction_cost": total_cost,
        "adverse_funding_cost": total_funding,
        "turnover": total_turnover,
        "rebalance_count": rebalance_count,
        "position_change_count": position_change_count,
        "average_gross_fraction": float(weights.abs().sum(axis=1).mean()),
        "symbol_gross_pnl": symbol_gross_pnl.to_dict(),
        "symbol_net_pnl": (symbol_gross_pnl - symbol_transaction_cost).to_dict(),
        "symbol_stressed_net_pnl": (
            symbol_gross_pnl - symbol_transaction_cost - symbol_funding_cost
        ).to_dict(),
        "symbol_double_cost_net_pnl": (
            symbol_gross_pnl - 2 * symbol_transaction_cost
        ).to_dict(),
        "equity_curve": rows,
    }


def aggregate_candidates(rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate fold rows and attach multiple-testing robustness gates."""

    records: list[dict[str, object]] = []
    for candidate, group in rows.groupby("candidate", sort=False):
        first = group.iloc[0]
        records.append(
            {
                "candidate": str(candidate),
                "neighborhood": str(first["neighborhood"]),
                "family": str(first["family"]),
                "timeframe": str(first["timeframe"]),
                "lookback_days": float(first["lookback_days"]),
                "side": str(first["side"]),
                "top_k": int(first["top_k"]),
                "absolute_gate": bool(first["absolute_gate"]),
                "volatility_managed": bool(first["volatility_managed"]),
                "net_pnl": float(group["net_pnl"].sum()),
                "stressed_net_pnl": float(group["stressed_net_pnl"].sum()),
                "double_cost_net_pnl": float(group["double_cost_net_pnl"].sum()),
                "positive_fold_count": int(group["net_pnl"].gt(0).sum()),
                "positive_double_cost_fold_count": int(
                    group["double_cost_net_pnl"].gt(0).sum()
                ),
                "fold_count": len(group),
                "worst_fold_net_pnl": float(group["net_pnl"].min()),
                "max_drawdown_percent": float(group["max_drawdown_percent"].max()),
                "rebalance_count": int(group["rebalance_count"].sum()),
                "position_change_count": int(group["position_change_count"].sum()),
                "transaction_cost": float(group["transaction_cost"].sum()),
                "adverse_funding_cost": float(group["adverse_funding_cost"].sum()),
            }
        )
    aggregate = pd.DataFrame.from_records(records)
    profitable = aggregate["double_cost_net_pnl"].gt(0)
    neighbor_ratio = profitable.groupby(aggregate["neighborhood"]).transform("mean")
    aggregate["positive_neighbor_ratio"] = neighbor_ratio
    aggregate["passed"] = (
        aggregate["positive_double_cost_fold_count"].eq(aggregate["fold_count"])
        & aggregate["stressed_net_pnl"].gt(0)
        & aggregate["double_cost_net_pnl"].gt(0)
        & aggregate["position_change_count"].ge(30)
        & aggregate["positive_neighbor_ratio"].ge(0.5)
    )
    return aggregate


def select_candidate(rows: pd.DataFrame) -> dict[str, Any]:
    """Select from training folds only using robustness before raw profit."""

    aggregate = aggregate_candidates(rows)
    if aggregate.empty:
        raise ValueError("cannot select a portfolio candidate from no rows")
    ranked = aggregate.sort_values(
        by=[
            "passed",
            "positive_double_cost_fold_count",
            "positive_neighbor_ratio",
            "double_cost_net_pnl",
            "stressed_net_pnl",
            "worst_fold_net_pnl",
            "max_drawdown_percent",
            "candidate",
        ],
        ascending=[False, False, False, False, False, False, True, True],
        kind="stable",
    )
    return cast(dict[str, Any], ranked.iloc[0].to_dict())


def family_leaders(aggregate: pd.DataFrame) -> pd.DataFrame:
    """Return one robust leader per family for diagnosis."""

    ordered = aggregate.sort_values(
        by=[
            "passed",
            "positive_double_cost_fold_count",
            "positive_neighbor_ratio",
            "double_cost_net_pnl",
            "max_drawdown_percent",
        ],
        ascending=[False, False, False, False, True],
        kind="stable",
    )
    return ordered.groupby("family", sort=False).head(1).reset_index(drop=True)


def _sign(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        np.sign(frame.fillna(0.0).to_numpy()),
        index=frame.index,
        columns=frame.columns,
    )


def _sign_series(values: pd.Series) -> pd.Series:
    return pd.Series(np.sign(values.to_numpy()), index=values.index)


def _cross_section_signal(
    returns: pd.DataFrame,
    *,
    top_k: int,
    reversal: bool,
    side: PortfolioSide,
    absolute_gate: bool,
) -> pd.DataFrame:
    if top_k * 2 > len(returns.columns):
        raise ValueError("top_k leaves no room for both portfolio sides")
    ranks = returns.rank(axis=1, method="first")
    long_mask = ranks.gt(len(returns.columns) - top_k)
    short_mask = ranks.le(top_k)
    if reversal:
        long_mask, short_mask = short_mask, long_mask
    if absolute_gate:
        long_mask &= returns.gt(0)
        short_mask &= returns.lt(0)
    signal = long_mask.astype(float) - short_mask.astype(float)
    if side is PortfolioSide.LONG_ONLY:
        signal = signal.clip(lower=0)
    return signal.where(returns.notna(), 0.0)


def _donchian_direction(market: PortfolioMarket, lookback: int) -> pd.DataFrame:
    upper = market.highs.shift(1).rolling(lookback).max()
    lower = market.lows.shift(1).rolling(lookback).min()
    events = pd.DataFrame(
        np.nan, index=market.closes.index, columns=market.closes.columns
    )
    events = events.mask(market.closes.gt(upper), 1.0)
    events = events.mask(market.closes.lt(lower), -1.0)
    return events.ffill().fillna(0.0)


def _funding_events(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    interval_hours: int,
) -> int:
    interval = pd.Timedelta(hours=interval_hours)
    first = start.ceil(interval)
    if first <= start:
        first += interval
    if first > end:
        return 0
    return int(math.floor(float((end - first) / interval)) + 1)
