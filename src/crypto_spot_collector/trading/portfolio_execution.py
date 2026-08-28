"""Execution boundary for the daily portfolio strategy."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from crypto_spot_collector.trading.config import (
    Network,
    SignalMode,
    TradingConfig,
)
from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderIntent,
    OrderStatus,
    create_intent,
)
from crypto_spot_collector.trading.portfolio_strategy import (
    DAY_MS,
    STRATEGY_NAME,
    DecisionStatus,
    PortfolioDecision,
    RebalancePhase,
    RebalancePlan,
    SQLitePortfolioDecisionStore,
    TrendEnsembleConfig,
    calculate_trend_ensemble_target,
    plan_rebalance,
)
from crypto_spot_collector.trading.protection import (
    ProtectionReconciler,
    ProtectionReport,
)


class PortfolioExecutionError(RuntimeError):
    """Raised when exchange truth cannot prove a safe portfolio step."""


class PreparedOrder(Protocol):
    amount: float
    reference_price: float


class PortfolioAdapter(Protocol):
    async def fetch_positions(self) -> Sequence[dict[str, Any]]: ...

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> Sequence[dict[str, Any]]: ...

    async def fetch_free_collateral(self) -> float: ...

    async def fetch_price_async(self, symbol: str) -> Mapping[str, Any]: ...

    async def prepare_market_order(
        self,
        symbol: str,
        amount: float,
        *,
        reference_price: float | None = None,
        max_notional: float | None = None,
    ) -> PreparedOrder: ...

    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str,
        fromDate: datetime,
        toDate: datetime,
    ) -> Any: ...


@dataclass(frozen=True)
class PortfolioExecutionReceipt:
    previous_plan: RebalancePlan
    order: OrderIntent | None
    protection: ProtectionReport | None
    next_plan: RebalancePlan


def trend_config_from_trading_config(config: TradingConfig) -> TrendEnsembleConfig:
    """Translate the validated deployment boundary into frozen strategy settings."""

    config.validate()
    if config.signal_mode is not SignalMode.PORTFOLIO_TREND_ENSEMBLE:
        raise ValueError("trading config is not for the portfolio trend ensemble")
    return TrendEnsembleConfig(
        symbols=config.symbols,
        gross_notional_usdc=config.max_total_notional_usdc,
        max_order_notional_usdc=config.max_order_notional_usdc,
        max_symbol_notional_usdc=config.max_symbol_notional_usdc,
        max_positions=config.max_positions,
        rebalance_tolerance_usdc=config.portfolio_rebalance_tolerance_usdc,
        max_decision_delay_seconds=config.portfolio_max_decision_delay_seconds,
    )


async def fetch_completed_portfolio_market(
    adapter: PortfolioAdapter,
    config: TrendEnsembleConfig,
    *,
    observed_at_ms: int,
    history_days: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fetch and align completed daily candles for every configured symbol."""

    if history_days < config.required_rows + 2:
        raise ValueError("history_days does not cover indicator warm-up")
    observed_at = datetime.fromtimestamp(observed_at_ms / 1_000, tz=timezone.utc)
    start = observed_at - timedelta(days=history_days)
    payloads = await asyncio.gather(
        *(
            adapter.fetch_ohlcv_async(symbol, "1d", start, observed_at)
            for symbol in config.symbols
        )
    )
    parsed = {
        symbol: _parse_completed_ohlcv(payload, observed_at_ms)
        for symbol, payload in zip(config.symbols, payloads, strict=True)
    }
    expected_index: pd.DatetimeIndex | None = None
    for symbol, frame in parsed.items():
        if expected_index is None:
            expected_index = frame.index
        elif not frame.index.equals(expected_index):
            raise ValueError(f"completed daily candles do not align for {symbol}")
    if expected_index is None:
        raise ValueError("no portfolio market data was returned")
    highs = pd.DataFrame(
        {symbol: frame["high"] for symbol, frame in parsed.items()},
        index=expected_index,
    )
    lows = pd.DataFrame(
        {symbol: frame["low"] for symbol, frame in parsed.items()},
        index=expected_index,
    )
    closes = pd.DataFrame(
        {symbol: frame["close"] for symbol, frame in parsed.items()},
        index=expected_index,
    )
    return highs, lows, closes


async def calculate_live_portfolio_decision(
    adapter: PortfolioAdapter,
    config: TrendEnsembleConfig,
    *,
    observed_at_ms: int,
) -> PortfolioDecision:
    highs, lows, closes = await fetch_completed_portfolio_market(
        adapter,
        config,
        observed_at_ms=observed_at_ms,
    )
    return calculate_trend_ensemble_target(
        highs=highs,
        lows=lows,
        closes=closes,
        observed_at_ms=observed_at_ms,
        config=config,
    )


def position_notionals(
    positions: Sequence[dict[str, Any]], symbols: Sequence[str]
) -> dict[str, float]:
    """Normalize one exchange position per symbol into signed mark notionals."""

    allowlist = set(symbols)
    result: dict[str, float] = {}
    for position in positions:
        contracts = abs(_finite_float(position.get("contracts") or 0, "contracts"))
        if contracts == 0:
            continue
        symbol = str(position.get("symbol") or "").upper()
        if symbol not in allowlist:
            raise PortfolioExecutionError(
                f"live position {symbol!r} is outside the portfolio allowlist"
            )
        if symbol in result:
            raise PortfolioExecutionError(
                f"multiple live positions returned for {symbol}"
            )
        side = str(position.get("side") or "").lower()
        if side not in {"long", "short"}:
            raise PortfolioExecutionError(f"invalid position side for {symbol}")
        price = _finite_float(
            position.get("markPrice")
            or position.get("entryPrice")
            or position.get("entry_price")
            or 0,
            "position price",
        )
        if price <= 0:
            raise PortfolioExecutionError(f"invalid position price for {symbol}")
        result[symbol] = contracts * price * (1 if side == "long" else -1)
    return result


class PortfolioExecutionCoordinator:
    """Execute one action, refresh exchange truth, protect, and re-plan."""

    def __init__(
        self,
        adapter: PortfolioAdapter,
        executor: IdempotentOrderExecutor,
        protection_reconciler: ProtectionReconciler,
        decision_store: SQLitePortfolioDecisionStore,
        trading_config: TradingConfig,
        *,
        kill_switch_path: Path | str,
    ) -> None:
        trading_config.validate()
        self.adapter = adapter
        self.executor = executor
        self.protection_reconciler = protection_reconciler
        self.decision_store = decision_store
        self.trading_config = trading_config
        self.strategy_config = trend_config_from_trading_config(trading_config)
        self.kill_switch_path = Path(kill_switch_path)

    async def execute_next(
        self,
        decision: PortfolioDecision,
        expected_plan: RebalancePlan,
    ) -> PortfolioExecutionReceipt:
        """Execute only the first action bound to the current position snapshot."""

        if self.trading_config.network is Network.MAINNET:
            raise PortfolioExecutionError(
                "mainnet portfolio runtime is observation-only"
            )

        before_positions = list(await self.adapter.fetch_positions())
        before_notionals = position_notionals(
            before_positions, self.strategy_config.symbols
        )
        actual_plan = plan_rebalance(decision, before_notionals, self.strategy_config)
        if actual_plan.plan_id != expected_plan.plan_id:
            raise PortfolioExecutionError(
                "position snapshot changed after the rebalance plan was created"
            )
        if actual_plan.phase is RebalancePhase.COMPLETE:
            self.decision_store.transition(
                decision.decision_id, DecisionStatus.COMPLETE
            )
            return PortfolioExecutionReceipt(
                previous_plan=actual_plan,
                order=None,
                protection=None,
                next_plan=actual_plan,
            )

        action = actual_plan.actions[0]
        if action.reduce_only:
            desired_status = DecisionStatus.REDUCING
        else:
            desired_status = DecisionStatus.INCREASING
            await self._validate_increase(action.notional_usdc)
        self.decision_store.transition(decision.decision_id, desired_status)

        ticker = await self.adapter.fetch_price_async(action.symbol)
        reference_price = _finite_float(
            ticker.get("last") or ticker.get("close") or 0,
            "reference price",
        )
        if reference_price <= 0:
            raise PortfolioExecutionError(
                f"invalid reference price for {action.symbol}"
            )
        prepared = await self.adapter.prepare_market_order(
            action.symbol,
            action.notional_usdc / reference_price,
            reference_price=reference_price,
            max_notional=min(
                action.notional_usdc,
                self.trading_config.max_order_notional_usdc,
            ),
        )
        intent = create_intent(
            strategy=(
                f"{STRATEGY_NAME}:{decision.decision_id[:12]}:"
                f"{actual_plan.plan_id[:12]}"
            ),
            symbol=action.symbol,
            timeframe="1d",
            candle_open_ms=decision.candle_close_ms - DAY_MS,
            side=action.side,
            amount=prepared.amount,
            reduce_only=action.reduce_only,
        )
        order = await self.executor.execute_confirmed(intent)
        _require_full_fill(order)

        after_positions = list(await self.adapter.fetch_positions())
        _require_progress(
            action.reduce_only, action.symbol, before_positions, after_positions
        )
        protection = await self.protection_reconciler.reconcile_symbol(
            action.symbol,
            positions=after_positions,
        )
        after_notionals = position_notionals(
            after_positions, self.strategy_config.symbols
        )
        next_plan = plan_rebalance(decision, after_notionals, self.strategy_config)
        next_status = {
            RebalancePhase.REDUCE: DecisionStatus.REDUCING,
            RebalancePhase.INCREASE: DecisionStatus.INCREASING,
            RebalancePhase.COMPLETE: DecisionStatus.COMPLETE,
        }[next_plan.phase]
        self.decision_store.transition(decision.decision_id, next_status)
        return PortfolioExecutionReceipt(
            previous_plan=actual_plan,
            order=order,
            protection=protection,
            next_plan=next_plan,
        )

    async def _validate_increase(self, notional_usdc: float) -> None:
        if not self.trading_config.entries_enabled:
            raise PortfolioExecutionError(
                "portfolio increases are disabled by configuration"
            )
        if self.kill_switch_path.exists():
            raise PortfolioExecutionError(
                "portfolio increases are stopped by kill switch"
            )
        free_collateral = _finite_float(
            await self.adapter.fetch_free_collateral(), "free collateral"
        )
        required_margin = notional_usdc / self.trading_config.leverage
        if (
            free_collateral - required_margin
            < self.trading_config.min_free_collateral_usdc
        ):
            raise PortfolioExecutionError(
                "free collateral would fall below the configured reserve"
            )
        orders = await self.adapter.fetch_open_orders(None)
        for order in orders:
            if not _is_reduce_only(order):
                raise PortfolioExecutionError(
                    "an unsettled non-reduce-only exchange order blocks an increase"
                )


def _parse_completed_ohlcv(payload: Any, observed_at_ms: int) -> pd.DataFrame:
    if isinstance(payload, Mapping):
        rows = list(payload.values())
    else:
        rows = list(payload)
    records: list[dict[str, float | int]] = []
    for raw in rows:
        if isinstance(raw, Mapping):
            timestamp = int(raw.get("timestamp") or raw.get("time") or 0)
            high = float(raw.get("high") or 0)
            low = float(raw.get("low") or 0)
            close = float(raw.get("close") or 0)
        else:
            timestamp = int(raw[0])
            high = float(raw[2])
            low = float(raw[3])
            close = float(raw[4])
        if timestamp + DAY_MS <= observed_at_ms:
            records.append(
                {"timestamp": timestamp, "high": high, "low": low, "close": close}
            )
    if not records:
        raise ValueError("no completed daily candles were returned")
    frame = pd.DataFrame.from_records(records)
    if frame["timestamp"].duplicated().any():
        raise ValueError("duplicate daily candle timestamps were returned")
    index = pd.to_datetime(frame.pop("timestamp"), unit="ms", utc=True)
    frame.index = pd.DatetimeIndex(index)
    return frame.sort_index()


def _require_full_fill(order: OrderIntent) -> None:
    if order.status is not OrderStatus.FILLED or not math.isclose(
        order.filled,
        order.amount,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise PortfolioExecutionError(
            f"portfolio intent {order.cloid} is not verifiably fully filled"
        )


def _require_progress(
    reduce_only: bool,
    symbol: str,
    before: Sequence[dict[str, Any]],
    after: Sequence[dict[str, Any]],
) -> None:
    before_contracts = _signed_contracts(before, symbol)
    after_contracts = _signed_contracts(after, symbol)
    if reduce_only:
        progressed = abs(after_contracts) < abs(before_contracts)
    elif before_contracts == 0:
        progressed = after_contracts != 0
    else:
        progressed = before_contracts * after_contracts > 0 and abs(
            after_contracts
        ) > abs(before_contracts)
    if not progressed:
        raise PortfolioExecutionError(
            f"exchange position for {symbol} did not progress in the planned direction"
        )


def _signed_contracts(positions: Sequence[dict[str, Any]], symbol: str) -> float:
    matching = [
        item
        for item in positions
        if str(item.get("symbol") or "").upper() == symbol
        and abs(float(item.get("contracts") or 0)) > 0
    ]
    if len(matching) > 1:
        raise PortfolioExecutionError(f"multiple positions returned for {symbol}")
    if not matching:
        return 0.0
    side = str(matching[0].get("side") or "").lower()
    contracts = abs(_finite_float(matching[0].get("contracts"), "contracts"))
    if side not in {"long", "short"}:
        raise PortfolioExecutionError(f"invalid position side for {symbol}")
    return contracts if side == "long" else -contracts


def _finite_float(value: Any, name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioExecutionError(f"{name} must be finite") from exc
    if not math.isfinite(normalized):
        raise PortfolioExecutionError(f"{name} must be finite")
    return normalized


def _is_reduce_only(order: Mapping[str, Any]) -> bool:
    info = order.get("info", {})
    if not isinstance(info, Mapping):
        info = {}
    nested = info.get("order", {})
    if not isinstance(nested, Mapping):
        nested = {}
    if bool(
        order.get(
            "reduceOnly",
            nested.get("reduceOnly", info.get("reduceOnly", False)),
        )
    ):
        return True
    order_type = str(
        nested.get("orderType") or info.get("orderType") or order.get("type") or ""
    ).lower()
    return "take profit" in order_type or "stop" in order_type
