"""Dedicated runtime for the frozen daily portfolio strategy."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.trading.config import (
    SignalMode,
    TradingConfig,
    next_timeframe_boundary,
)
from crypto_spot_collector.trading.deployment import (
    RuntimeState,
    required_runtime_path,
    validate_deployment_secrets,
)
from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderStatus,
    SQLiteOrderIntentStore,
)
from crypto_spot_collector.trading.portfolio_execution import (
    PortfolioExecutionCoordinator,
    PortfolioExecutionError,
    calculate_live_portfolio_decision,
    position_notionals,
    trend_config_from_trading_config,
)
from crypto_spot_collector.trading.portfolio_strategy import (
    DecisionStatus,
    PortfolioDecision,
    RebalancePhase,
    SQLitePortfolioDecisionStore,
    plan_rebalance,
)
from crypto_spot_collector.trading.protection import ProtectionReconciler
from crypto_spot_collector.trading.runtime import RuntimeSupervisor
from crypto_spot_collector.utils.secrets import load_config

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logger.remove()
logger.add(sys.stdout, level="INFO")
logger.add(
    LOG_DIR / "buy_portfolio_{time:YYYYMMDD}.log",
    level="DEBUG",
    rotation="00:00",
    retention="30 days",
    compression="zip",
)


class PortfolioApplication:
    def __init__(
        self,
        *,
        config: TradingConfig,
        exchange: HyperLiquidExchange,
        runtime_state: RuntimeState,
        order_executor: IdempotentOrderExecutor,
        decision_store: SQLitePortfolioDecisionStore,
        coordinator: PortfolioExecutionCoordinator,
    ) -> None:
        self.config = config
        self.exchange = exchange
        self.runtime_state = runtime_state
        self.order_executor = order_executor
        self.decision_store = decision_store
        self.coordinator = coordinator
        self.strategy_config = trend_config_from_trading_config(config)

    async def initialize(self) -> None:
        await self.exchange.validate_api_wallet_authorization()
        if not self.config.entries_enabled:
            await self._require_flat_observer_account()
            unsettled = self.order_executor.store.list_unsettled()
            if unsettled:
                raise RuntimeError(
                    "observation-only startup is inhibited by unsettled order "
                    "intent(s): "
                    + ", ".join(order.cloid for order in unsettled)
                )
            latest = self.decision_store.latest()
            if latest is not None and latest.status not in {
                DecisionStatus.COMPLETE,
                DecisionStatus.BLOCKED,
            }:
                raise RuntimeError(
                    "an unfinished portfolio decision exists while execution is disabled"
                )
            logger.info(
                "Portfolio observer initialized: network={}, execution_enabled=false",
                self.config.network.value,
            )
            return
        recovered = await self.order_executor.recover_unsettled()
        unresolved = [
            order
            for order in recovered
            if order.status
            not in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        ]
        if unresolved:
            raise RuntimeError(
                "startup is inhibited by unresolved order intent(s): "
                + ", ".join(order.cloid for order in unresolved)
            )
        await self.coordinator.protection_reconciler.reconcile_all(
            self.strategy_config.symbols
        )
        latest = self.decision_store.latest()
        if latest is not None and latest.status not in {
            DecisionStatus.COMPLETE,
            DecisionStatus.BLOCKED,
        }:
            await self.execute_to_completion(latest.decision)

    async def _require_flat_observer_account(self) -> None:
        positions = list(await self.exchange.fetch_positions())
        notionals = position_notionals(positions, self.strategy_config.symbols)
        if any(value != 0 for value in notionals.values()):
            raise PortfolioExecutionError(
                "observation-only portfolio runtime requires a flat account"
            )
        if list(await self.exchange.fetch_open_orders()):
            raise PortfolioExecutionError(
                "observation-only portfolio runtime requires zero open orders"
            )

    async def run_cycle(self, *, observed_at_ms: int | None = None) -> None:
        observed = observed_at_ms or int(datetime.now(timezone.utc).timestamp() * 1_000)
        decision = await calculate_live_portfolio_decision(
            self.exchange,
            self.strategy_config,
            observed_at_ms=observed,
        )
        positions = list(await self.exchange.fetch_positions())
        notionals = position_notionals(positions, self.strategy_config.symbols)
        plan = plan_rebalance(decision, notionals, self.strategy_config)
        logger.info(
            "Portfolio decision prepared: candle_close_ms={}, phase={}, actions={}, "
            "gross_target_usdc={:.4f}, execution_enabled={}",
            decision.candle_close_ms,
            plan.phase.value,
            len(plan.actions),
            sum(abs(value) for value in decision.target_notionals.values()),
            self.config.entries_enabled,
        )
        if not self.config.entries_enabled:
            if any(value != 0 for value in notionals.values()):
                raise PortfolioExecutionError(
                    "observation-only portfolio runtime requires a flat account"
                )
            if list(await self.exchange.fetch_open_orders()):
                raise PortfolioExecutionError(
                    "observation-only portfolio runtime requires zero open orders"
                )
            return
        stored, _ = self.decision_store.prepare(decision)
        if stored.status is DecisionStatus.BLOCKED:
            raise RuntimeError("the current portfolio decision is operator-blocked")
        if stored.status is DecisionStatus.COMPLETE:
            logger.info(
                "Portfolio decision was already completed for candle_close_ms={}",
                decision.candle_close_ms,
            )
            return
        await self.execute_to_completion(stored.decision)

    async def execute_to_completion(
        self, decision: PortfolioDecision, *, maximum_steps: int = 100
    ) -> None:
        for _ in range(maximum_steps):
            positions = list(await self.exchange.fetch_positions())
            notionals = position_notionals(positions, self.strategy_config.symbols)
            plan = plan_rebalance(decision, notionals, self.strategy_config)
            receipt = await self.coordinator.execute_next(decision, plan)
            if receipt.next_plan.phase is RebalancePhase.COMPLETE:
                logger.info(
                    "Portfolio rebalance complete: decision_id={}",
                    decision.decision_id,
                )
                return
        raise RuntimeError("portfolio rebalance exceeded the maximum action count")

    async def cycle_loop(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            seconds_since_daily_close = (
                now - now.replace(hour=0, minute=0, second=0, microsecond=0)
            ).total_seconds()
            if seconds_since_daily_close < 120:
                await asyncio.sleep(max(1.0, 120 - seconds_since_daily_close))
                continue
            if (
                seconds_since_daily_close
                <= self.config.portfolio_max_decision_delay_seconds
            ):
                await self.run_cycle(observed_at_ms=int(now.timestamp() * 1_000))
            else:
                logger.info(
                    "Latest daily candle is outside the execution window; "
                    "waiting for the next UTC close"
                )
            boundary = next_timeframe_boundary(now, self.config.timeframe)
            next_run = boundary + timedelta(minutes=2)
            wait_seconds = max(
                1.0, (next_run - datetime.now(timezone.utc)).total_seconds()
            )
            await asyncio.sleep(wait_seconds)

    async def health_loop(self) -> None:
        while True:
            self.runtime_state.health.write("running")
            await asyncio.sleep(20)


def build_application() -> PortfolioApplication:
    secret_file = required_runtime_path("HYPERLIQUID_SECRETS_FILE")
    settings_file = required_runtime_path("HYPERLIQUID_SETTINGS_FILE")
    state_directory = required_runtime_path("HYPERLIQUID_STATE_DIR")
    secrets = load_config(secret_file, settings_file)
    config = TradingConfig.from_mapping(
        secrets["settings"],
        mainnet_confirmation=os.getenv("HYPERLIQUID_MAINNET_CONFIRMATION", ""),
    )
    if config.signal_mode is not SignalMode.PORTFOLIO_TREND_ENSEMBLE:
        raise ValueError("buy_portfolio requires portfolio_trend_ensemble settings")
    deployment_secrets = validate_deployment_secrets(
        secrets,
        config,
        expected_network=os.getenv("HYPERLIQUID_DEPLOYMENT_NETWORK", ""),
    )
    runtime_state = RuntimeState.open(
        state_directory,
        wallet_address=deployment_secrets["mainWalletAddress"],
        config=config,
    )
    exchange = HyperLiquidExchange(
        mainWalletAddress=deployment_secrets["mainWalletAddress"],
        apiWalletAddress=deployment_secrets["apiWalletAddress"],
        privateKey=deployment_secrets["privatekey"],
        trading_config=config,
    )
    order_store = SQLiteOrderIntentStore(runtime_state.database_path)
    decision_store = SQLitePortfolioDecisionStore(runtime_state.database_path)
    order_executor = IdempotentOrderExecutor(exchange, order_store)
    protection = ProtectionReconciler(
        exchange,
        take_profit_roe=config.take_profit_roe,
        stop_loss_roe=config.stop_loss_roe,
        leverage=config.leverage,
    )
    kill_switch = Path(config.entry_kill_switch_file)
    if not kill_switch.is_absolute():
        kill_switch = state_directory / kill_switch
    coordinator = PortfolioExecutionCoordinator(
        exchange,
        order_executor,
        protection,
        decision_store,
        config,
        kill_switch_path=kill_switch,
    )
    return PortfolioApplication(
        config=config,
        exchange=exchange,
        runtime_state=runtime_state,
        order_executor=order_executor,
        decision_store=decision_store,
        coordinator=coordinator,
    )


async def main() -> None:
    application = build_application()
    supervisor = RuntimeSupervisor(
        [application.runtime_state, application.exchange],
        on_shutdown_requested=application.order_executor.stop_accepting,
    )
    supervisor.install_signal_handlers()
    try:
        await application.initialize()
        application.runtime_state.health.write("running")
        await supervisor.run([application.cycle_loop(), application.health_loop()])
    finally:
        await supervisor.close()


if __name__ == "__main__":
    asyncio.run(main())
