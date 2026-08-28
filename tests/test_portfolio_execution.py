from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import crypto_spot_collector.apps.buy_portfolio as portfolio_app_module
from crypto_spot_collector.apps.buy_portfolio import PortfolioApplication
from crypto_spot_collector.trading.config import (
    MAINNET_CONFIRMATION,
    Network,
    SignalMode,
    TradingConfig,
)
from crypto_spot_collector.trading.order_state import OrderIntent, OrderStatus
from crypto_spot_collector.trading.portfolio_execution import (
    PortfolioExecutionCoordinator,
    PortfolioExecutionError,
    fetch_completed_portfolio_market,
    position_notionals,
    trend_config_from_trading_config,
)
from crypto_spot_collector.trading.portfolio_strategy import (
    DAY_MS,
    SELECTED_PORTFOLIO_SYMBOLS,
    DecisionStatus,
    PortfolioDecision,
    PortfolioTarget,
    RebalancePhase,
    SQLitePortfolioDecisionStore,
    plan_rebalance,
)
from crypto_spot_collector.trading.protection import ProtectionReport

BTC = SELECTED_PORTFOLIO_SYMBOLS[0]


def trading_config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": SELECTED_PORTFOLIO_SYMBOLS,
        "timeframe": "1d",
        "amount_usdc": 12.5,
        "leverage": 1,
        "take_profit_roe": 15.0,
        "stop_loss_roe": 3.0,
        "trailing_interval_minutes": 15,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 1,
        "sar_close_consecutive_count": 1,
        "price_change_threshold_percent": 999.0,
        "max_order_notional_usdc": 12.5,
        "max_symbol_notional_usdc": 75.0,
        "max_total_notional_usdc": 75.0,
        "max_positions": 6,
        "max_leverage": 1,
        "min_free_collateral_usdc": 25.0,
        "signal_mode": SignalMode.PORTFOLIO_TREND_ENSEMBLE,
        "network": Network.TESTNET,
        "portfolio_rebalance_tolerance_usdc": 0.25,
    }
    values.update(overrides)
    config = TradingConfig(**values)  # type: ignore[arg-type]
    config.validate()
    return config


def decision(btc_target: float) -> PortfolioDecision:
    notionals = [btc_target, 20.0, 15.0, 10.0, 5.0, 5.0]
    targets = tuple(
        PortfolioTarget(
            symbol=symbol,
            momentum_direction=1 if value > 0 else -1 if value < 0 else 0,
            ema_direction=1 if value > 0 else -1 if value < 0 else 0,
            donchian_direction=0,
            votes=2 if value > 0 else -2 if value < 0 else 0,
            daily_volatility=0.02,
            weight=value / 75,
            signed_notional_usdc=value,
        )
        for symbol, value in zip(SELECTED_PORTFOLIO_SYMBOLS, notionals, strict=True)
    )
    return PortfolioDecision(
        decision_id="portfolio-decision",
        strategy="daily_trend_ensemble_v1",
        candle_close_ms=DAY_MS,
        observed_at_ms=DAY_MS,
        gross_notional_usdc=75,
        targets=targets,
    )


def position(
    *, symbol: str = BTC, side: str = "long", contracts: float = 0.2
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "contracts": contracts,
        "markPrice": 100.0,
        "entryPrice": 100.0,
        "leverage": 1,
    }


class FakeAdapter:
    def __init__(self, positions: list[dict[str, Any]] | None = None) -> None:
        self.positions = list(positions or [])
        self.orders: list[dict[str, Any]] = []
        self.free_collateral = 1_000.0
        self.ohlcv: dict[str, list[list[float]]] = {}
        self.authorization_checks = 0

    async def validate_api_wallet_authorization(self) -> None:
        self.authorization_checks += 1

    async def fetch_positions(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.positions]

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        if symbol is None:
            return list(self.orders)
        return [item for item in self.orders if item.get("symbol") == symbol]

    async def fetch_free_collateral(self) -> float:
        return self.free_collateral

    async def fetch_price_async(self, symbol: str) -> dict[str, float]:
        return {"last": 100.0}

    async def prepare_market_order(
        self,
        symbol: str,
        amount: float,
        *,
        reference_price: float | None = None,
        max_notional: float | None = None,
    ) -> SimpleNamespace:
        assert amount * float(reference_price or 0) <= float(max_notional or 0) + 1e-9
        return SimpleNamespace(amount=amount, reference_price=reference_price)

    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str,
        fromDate: datetime,
        toDate: datetime,
    ) -> list[list[float]]:
        assert timeframe == "1d"
        return list(self.ohlcv[symbol])


class MutatingExecutor:
    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter
        self.intents: list[OrderIntent] = []

    async def execute_confirmed(self, intent: OrderIntent) -> OrderIntent:
        self.intents.append(intent)
        existing = next(
            (
                item
                for item in self.adapter.positions
                if item["symbol"] == intent.symbol
            ),
            None,
        )
        signed_amount = intent.amount if intent.side == "buy" else -intent.amount
        if existing is None:
            self.adapter.positions.append(
                position(
                    symbol=intent.symbol,
                    side="long" if signed_amount > 0 else "short",
                    contracts=abs(signed_amount),
                )
            )
        else:
            current = float(existing["contracts"]) * (
                1 if existing["side"] == "long" else -1
            )
            updated = current + signed_amount
            if math_is_zero(updated):
                self.adapter.positions.remove(existing)
            else:
                existing["side"] = "long" if updated > 0 else "short"
                existing["contracts"] = abs(updated)
        return replace(
            intent,
            status=OrderStatus.FILLED,
            filled=intent.amount,
            order_id="order-1",
        )


class FakeProtection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []

    async def reconcile_symbol(
        self,
        symbol: str,
        *,
        positions: list[dict[str, Any]],
    ) -> ProtectionReport:
        self.calls.append((symbol, positions))
        return ProtectionReport(symbol=symbol, position=None)


def math_is_zero(value: float) -> bool:
    return abs(value) < 1e-12


def coordinator(
    tmp_path: Path,
    adapter: FakeAdapter,
    *,
    config: TradingConfig | None = None,
) -> tuple[
    PortfolioExecutionCoordinator,
    SQLitePortfolioDecisionStore,
    MutatingExecutor,
    FakeProtection,
]:
    actual_config = config or trading_config()
    store = SQLitePortfolioDecisionStore(tmp_path / "state.sqlite3")
    executor = MutatingExecutor(adapter)
    protection = FakeProtection()
    result = PortfolioExecutionCoordinator(
        adapter,
        executor,  # type: ignore[arg-type]
        protection,  # type: ignore[arg-type]
        store,
        actual_config,
        kill_switch_path=tmp_path / "ENTRY_KILL_SWITCH",
    )
    return result, store, executor, protection


def test_portfolio_config_allows_only_disabled_mainnet_observer_and_is_frozen() -> None:
    mainnet = trading_config(
        network=Network.MAINNET,
        allow_mainnet=True,
        mainnet_confirmation=MAINNET_CONFIRMATION,
        entries_enabled=False,
    )
    assert mainnet.network is Network.MAINNET
    with pytest.raises(ValueError, match="entries_enabled=false"):
        trading_config(
            network=Network.MAINNET,
            allow_mainnet=True,
            mainnet_confirmation=MAINNET_CONFIRMATION,
            entries_enabled=True,
        )
    with pytest.raises(ValueError, match="frozen set"):
        trading_config(symbols=tuple(reversed(SELECTED_PORTFOLIO_SYMBOLS)))
    with pytest.raises(ValueError, match="timeframe=1d"):
        trading_config(timeframe="4h")
    with pytest.raises(ValueError, match="1x leverage"):
        trading_config(leverage=2, max_leverage=2)
    with pytest.raises(ValueError, match="full gross cap"):
        trading_config(max_symbol_notional_usdc=35)


def test_trading_config_maps_to_frozen_strategy_limits() -> None:
    result = trend_config_from_trading_config(trading_config())
    assert result.symbols == SELECTED_PORTFOLIO_SYMBOLS
    assert result.gross_notional_usdc == 75
    assert result.max_order_notional_usdc == 12.5
    assert result.max_symbol_notional_usdc == 75


def test_position_notionals_rejects_unknown_or_duplicate_positions() -> None:
    assert position_notionals([position()], SELECTED_PORTFOLIO_SYMBOLS) == {BTC: 20}
    with pytest.raises(PortfolioExecutionError, match="outside"):
        position_notionals(
            [position(symbol="UNKNOWN/USDC:USDC")], SELECTED_PORTFOLIO_SYMBOLS
        )
    with pytest.raises(PortfolioExecutionError, match="multiple"):
        position_notionals([position(), position()], SELECTED_PORTFOLIO_SYMBOLS)


@pytest.mark.asyncio
async def test_reduce_step_is_partial_refreshes_and_reconciles_protection(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([position()])
    runtime, store, executor, protection = coordinator(tmp_path, adapter)
    target = decision(-20)
    store.prepare(target)
    initial = plan_rebalance(
        target,
        position_notionals(adapter.positions, SELECTED_PORTFOLIO_SYMBOLS),
        runtime.strategy_config,
    )

    receipt = await runtime.execute_next(target, initial)

    assert initial.phase is RebalancePhase.REDUCE
    assert executor.intents[0].reduce_only is True
    assert adapter.positions[0]["contracts"] == pytest.approx(0.075)
    assert receipt.next_plan.plan_id != initial.plan_id
    assert receipt.next_plan.phase is RebalancePhase.REDUCE
    assert protection.calls[0][0] == BTC


@pytest.mark.asyncio
async def test_increase_step_requires_enabled_fresh_safe_snapshot(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    runtime, store, executor, protection = coordinator(tmp_path, adapter)
    target = decision(20)
    store.prepare(target)
    initial = plan_rebalance(target, {}, runtime.strategy_config)

    receipt = await runtime.execute_next(target, initial)

    assert executor.intents[0].reduce_only is False
    assert adapter.positions[0]["side"] == "long"
    assert adapter.positions[0]["contracts"] == pytest.approx(0.125)
    assert receipt.next_plan.phase is RebalancePhase.INCREASE
    assert protection.calls


@pytest.mark.asyncio
async def test_increase_is_blocked_by_disabled_entries_kill_switch_or_order(
    tmp_path: Path,
) -> None:
    target = decision(20)

    disabled_adapter = FakeAdapter()
    disabled, disabled_store, _, _ = coordinator(
        tmp_path / "disabled",
        disabled_adapter,
        config=trading_config(entries_enabled=False),
    )
    disabled_store.prepare(target)
    with pytest.raises(PortfolioExecutionError, match="disabled"):
        await disabled.execute_next(
            target, plan_rebalance(target, {}, disabled.strategy_config)
        )

    killed_adapter = FakeAdapter()
    killed, killed_store, _, _ = coordinator(tmp_path / "killed", killed_adapter)
    killed.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
    killed.kill_switch_path.touch()
    killed_store.prepare(target)
    with pytest.raises(PortfolioExecutionError, match="kill switch"):
        await killed.execute_next(
            target, plan_rebalance(target, {}, killed.strategy_config)
        )

    order_adapter = FakeAdapter()
    order_adapter.orders = [{"symbol": BTC, "reduceOnly": False}]
    ordered, ordered_store, _, _ = coordinator(tmp_path / "ordered", order_adapter)
    ordered_store.prepare(target)
    with pytest.raises(PortfolioExecutionError, match="non-reduce-only"):
        await ordered.execute_next(
            target, plan_rebalance(target, {}, ordered.strategy_config)
        )


@pytest.mark.asyncio
async def test_mainnet_coordinator_blocks_every_execution_path(tmp_path: Path) -> None:
    adapter = FakeAdapter([position()])
    mainnet = trading_config(
        network=Network.MAINNET,
        allow_mainnet=True,
        mainnet_confirmation=MAINNET_CONFIRMATION,
        entries_enabled=False,
    )
    runtime, store, executor, protection = coordinator(
        tmp_path, adapter, config=mainnet
    )
    target = decision(0)
    store.prepare(target)

    with pytest.raises(PortfolioExecutionError, match="observation-only"):
        await runtime.execute_next(
            target,
            plan_rebalance(
                target,
                position_notionals(adapter.positions, SELECTED_PORTFOLIO_SYMBOLS),
                runtime.strategy_config,
            ),
        )

    assert executor.intents == []
    assert protection.calls == []


@pytest.mark.asyncio
async def test_nested_reduce_only_protection_does_not_block_increase(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    adapter.orders = [
        {
            "symbol": SELECTED_PORTFOLIO_SYMBOLS[1],
            "info": {
                "order": {
                    "reduceOnly": True,
                    "orderType": "Stop Market",
                }
            },
        }
    ]
    runtime, store, executor, _ = coordinator(tmp_path, adapter)
    target = decision(20)
    store.prepare(target)

    await runtime.execute_next(
        target, plan_rebalance(target, {}, runtime.strategy_config)
    )

    assert executor.intents


@pytest.mark.asyncio
async def test_changed_position_snapshot_invalidates_plan(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    runtime, store, _, _ = coordinator(tmp_path, adapter)
    target = decision(20)
    store.prepare(target)
    stale = plan_rebalance(target, {}, runtime.strategy_config)
    adapter.positions = [position(contracts=0.01)]

    with pytest.raises(PortfolioExecutionError, match="snapshot changed"):
        await runtime.execute_next(target, stale)


@pytest.mark.asyncio
async def test_market_fetch_filters_incomplete_bar_and_requires_alignment() -> None:
    adapter = FakeAdapter()
    observed = int(datetime(2026, 5, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000)
    index = pd.date_range("2026-01-20", "2026-05-01", freq="1D", tz="UTC")
    for number, symbol in enumerate(SELECTED_PORTFOLIO_SYMBOLS, start=1):
        adapter.ohlcv[symbol] = [
            [
                float(timestamp.timestamp() * 1_000),
                100.0,
                102.0 + number,
                98.0,
                100.0 + np.sin(offset / 4),
                1.0,
            ]
            for offset, timestamp in enumerate(index)
        ]
    settings = trend_config_from_trading_config(trading_config())

    highs, lows, closes = await fetch_completed_portfolio_market(
        adapter, settings, observed_at_ms=observed
    )

    assert highs.index[-1] == pd.Timestamp("2026-04-30", tz="UTC")
    assert lows.index.equals(highs.index)
    assert closes.columns.tolist() == list(SELECTED_PORTFOLIO_SYMBOLS)

    adapter.ohlcv[SELECTED_PORTFOLIO_SYMBOLS[-1]].pop(-2)
    with pytest.raises(ValueError, match="do not align"):
        await fetch_completed_portfolio_market(
            adapter, settings, observed_at_ms=observed
        )


@pytest.mark.asyncio
async def test_disabled_application_cycle_is_read_only_for_decision_and_orders(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    observed = int(datetime(2026, 5, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000)
    index = pd.date_range("2026-01-20", "2026-05-01", freq="1D", tz="UTC")
    for number, symbol in enumerate(SELECTED_PORTFOLIO_SYMBOLS, start=1):
        adapter.ohlcv[symbol] = [
            [
                float(timestamp.timestamp() * 1_000),
                100.0,
                103.0 + number,
                97.0,
                100.0 + np.sin(offset / (3 + number)),
                1.0,
            ]
            for offset, timestamp in enumerate(index)
        ]
    disabled_config = trading_config(entries_enabled=False)
    store = SQLitePortfolioDecisionStore(tmp_path / "disabled.sqlite3")
    executor = SimpleNamespace(intents=[])
    application = PortfolioApplication(
        config=disabled_config,
        exchange=adapter,  # type: ignore[arg-type]
        runtime_state=SimpleNamespace(),  # type: ignore[arg-type]
        order_executor=executor,  # type: ignore[arg-type]
        decision_store=store,
        coordinator=SimpleNamespace(),  # type: ignore[arg-type]
    )

    await application.run_cycle(observed_at_ms=observed)

    assert store.latest() is None
    assert executor.intents == []


@pytest.mark.asyncio
async def test_disabled_application_initialization_is_observation_only(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter()
    decision_store = SQLitePortfolioDecisionStore(tmp_path / "observer.sqlite3")

    class NoRecoveryExecutor:
        def __init__(self) -> None:
            self.store = SimpleNamespace(list_unsettled=lambda: [])

        async def recover_unsettled(self) -> None:
            raise AssertionError("disabled observer must not recover live orders")

    class NoProtection:
        async def reconcile_all(self, symbols: object) -> None:
            raise AssertionError("disabled observer must not reconcile protection")

    application = PortfolioApplication(
        config=trading_config(entries_enabled=False),
        exchange=adapter,  # type: ignore[arg-type]
        runtime_state=SimpleNamespace(),  # type: ignore[arg-type]
        order_executor=NoRecoveryExecutor(),  # type: ignore[arg-type]
        decision_store=decision_store,
        coordinator=SimpleNamespace(protection_reconciler=NoProtection()),  # type: ignore[arg-type]
    )

    await application.initialize()

    assert adapter.authorization_checks == 1
    assert adapter.positions == []
    assert adapter.orders == []


@pytest.mark.asyncio
async def test_completed_daily_decision_is_not_replayed_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = decision(20)
    store = SQLitePortfolioDecisionStore(tmp_path / "completed.sqlite3")
    store.prepare(target)
    store.transition(target.decision_id, DecisionStatus.COMPLETE)
    adapter = FakeAdapter()
    application = PortfolioApplication(
        config=trading_config(entries_enabled=True),
        exchange=adapter,  # type: ignore[arg-type]
        runtime_state=SimpleNamespace(),  # type: ignore[arg-type]
        order_executor=SimpleNamespace(),  # type: ignore[arg-type]
        decision_store=store,
        coordinator=SimpleNamespace(),  # type: ignore[arg-type]
    )

    async def same_decision(*args: object, **kwargs: object) -> PortfolioDecision:
        return target

    async def reject_replay(*args: object, **kwargs: object) -> None:
        raise AssertionError("completed decision was replayed")

    monkeypatch.setattr(
        portfolio_app_module, "calculate_live_portfolio_decision", same_decision
    )
    monkeypatch.setattr(application, "execute_to_completion", reject_replay)

    await application.run_cycle(observed_at_ms=DAY_MS)

    assert store.latest() is not None
    assert store.latest().status is DecisionStatus.COMPLETE
