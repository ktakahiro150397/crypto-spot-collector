"""Run the production SAR runtime path against HyperLiquid testnet.

This is intentionally destructive for one initially-flat testnet symbol.  It
uses controlled closed candles to exercise the same ``buy_perp`` strategy,
durable executor, protection reconciler, trailing manager and runtime
supervisor used by the deployed process.  It can never select mainnet.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.trading.config import Network, SignalMode, TradingConfig
from crypto_spot_collector.trading.order_state import create_intent
from crypto_spot_collector.trading.runtime import RuntimeSupervisor

APP_MODULE = "crypto_spot_collector.apps.buy_perp"
SYMBOL_CANDIDATES = (
    "ARB/USDC:USDC",
    "SOL/USDC:USDC",
    "ETH/USDC:USDC",
    "BTC/USDC:USDC",
    "HYPE/USDC:USDC",
)
TIMEFRAME = "1m"
LEVERAGE = 3
ORDER_NOTIONAL_USDC = 12.5


class _SilentNotifier:
    """Keep acceptance evidence local without sending account data externally."""

    async def send_notification_async(self, **_kwargs: Any) -> bool:
        return True

    async def send_notification_embed_with_file(self, **_kwargs: Any) -> bool:
        return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_position(
    positions: list[dict[str, Any]], symbol: str
) -> dict[str, Any] | None:
    return next(
        (
            position
            for position in positions
            if position.get("symbol") == symbol
            and abs(float(position.get("contracts") or 0)) > 0
        ),
        None,
    )


def _is_protection(order: dict[str, Any]) -> bool:
    info = order.get("info", {}) or {}
    order_type = str(info.get("orderType") or order.get("type") or "").lower()
    return "take profit" in order_type or "stop" in order_type


async def _wait_for_position(
    exchange: HyperLiquidExchange,
    symbol: str,
    expected_side: str | None,
    *,
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        position = _active_position(list(await exchange.fetch_positions()), symbol)
        if expected_side is None and position is None:
            return None
        if position is not None and position.get("side") == expected_side:
            return position
        await asyncio.sleep(0.5)
    raise TimeoutError(f"position did not become {expected_side or 'flat'}: {symbol}")


async def _select_flat_symbol(
    wallet: str, private_key: str
) -> tuple[str, list[dict[str, Any]]]:
    config = TradingConfig(
        symbols=SYMBOL_CANDIDATES,
        timeframe=TIMEFRAME,
        amount_usdc=ORDER_NOTIONAL_USDC,
        leverage=LEVERAGE,
        take_profit_roe=15.0,
        stop_loss_roe=3.0,
        trailing_interval_minutes=1,
        trailing_activation_roe=0.01,
        sar_consecutive_count=1,
        sar_close_consecutive_count=1,
        price_change_threshold_percent=999.0,
        max_order_notional_usdc=25.0,
        max_symbol_notional_usdc=25.0,
        max_total_notional_usdc=100.0,
        max_positions=len(SYMBOL_CANDIDATES),
        max_leverage=LEVERAGE,
        min_free_collateral_usdc=0.0,
        network=Network.TESTNET,
    )
    exchange = HyperLiquidExchange(
        mainWalletAddress=wallet,
        apiWalletAddress=wallet,
        privateKey=private_key,
        trading_config=config,
    )
    try:
        positions = list(await exchange.fetch_positions())
        active = [
            position
            for position in positions
            if abs(float(position.get("contracts") or 0)) > 0
        ]
        open_orders = list(await exchange.fetch_open_orders(None))
        if active or open_orders:
            raise RuntimeError(
                "testnet account must be globally flat with no open orders before "
                "production-path acceptance"
            )
        symbol = next(
            (
                candidate
                for candidate in SYMBOL_CANDIDATES
                if _active_position(positions, candidate) is None
            ),
            None,
        )
        if symbol is None:
            raise RuntimeError("no configured acceptance symbol is flat")
        return symbol, active
    finally:
        await exchange.close()


def _write_runtime_files(
    directory: Path,
    *,
    wallet: str,
    private_key: str,
    symbol: str,
) -> tuple[Path, Path, Path]:
    secrets_path = directory / "testnet-secrets.json"
    settings_path = directory / "testnet-settings.json"
    state_path = directory / "state"
    secrets_path.write_text(
        json.dumps(
            {
                "discord": {
                    "discordWebhookUrlPerpetual": "disabled://testnet-acceptance"
                },
                "hyperliquid": {
                    "network": "testnet",
                    "mainWalletAddress": wallet,
                    "apiWalletAddress": wallet,
                    "privatekey": private_key,
                },
            }
        ),
        encoding="utf-8",
    )
    settings_path.write_text(
        json.dumps(
            {
                "settings": {
                    "network": "testnet",
                    "sandbox_mode": True,
                    "allow_mainnet": False,
                    "perpetual": {
                        "symbols": [symbol],
                        "signal_mode": "sar_only",
                        "canary_mode": True,
                        "entries_enabled": True,
                        "entry_kill_switch_file": "ENTRY_KILL_SWITCH",
                        "timeframe": TIMEFRAME,
                        "leverage": LEVERAGE,
                        "margin_mode": "cross",
                        "take_profit_rate": 15.0,
                        "stop_loss_rate": 3.0,
                        "amountByUSDC": ORDER_NOTIONAL_USDC,
                        "consecutivePositiveCount": 1,
                        "sar_close_consecutive_count": 1,
                        "price_change_threshold_percent": 999.0,
                        "trailing_stop_interval_minutes": 1,
                        "trailing_stop_activation_pnl_percent": 0.01,
                        "risk": {
                            "max_order_notional_usdc": 25.0,
                            "max_symbol_notional_usdc": 25.0,
                            "max_total_notional_usdc": 25.0,
                            "max_positions": 1,
                            "max_leverage": LEVERAGE,
                            "min_free_collateral_usdc": 0.0,
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return secrets_path, settings_path, state_path


def _load_production_app(
    secrets_path: Path, settings_path: Path, state_path: Path
) -> ModuleType:
    os.environ["HYPERLIQUID_SECRETS_FILE"] = str(secrets_path)
    os.environ["HYPERLIQUID_SETTINGS_FILE"] = str(settings_path)
    os.environ["HYPERLIQUID_STATE_DIR"] = str(state_path)
    os.environ["HYPERLIQUID_DEPLOYMENT_NETWORK"] = "testnet"
    os.environ.pop("HYPERLIQUID_MAINNET_CONFIRMATION", None)
    sys.modules.pop(APP_MODULE, None)
    app = importlib.import_module(APP_MODULE)
    if (
        not app.trading_config.testnet
        or app.trading_config.network is not Network.TESTNET
    ):
        raise RuntimeError("acceptance runtime did not select testnet")
    if app.trading_config.signal_mode is not SignalMode.SAR_ONLY:
        raise RuntimeError("acceptance runtime did not select SAR-only strategy")
    setattr(app, "notificator", _SilentNotifier())
    return app


def _controlled_frame(
    end: datetime,
    *,
    direction: str,
    reference_price: float,
    stale: bool = False,
) -> pd.DataFrame:
    if direction not in {"long", "short"}:
        raise ValueError("controlled direction must be long or short")
    timestamps = [end - timedelta(minutes=2), end - timedelta(minutes=1)]
    if direction == "long":
        sar_up = [reference_price * 0.99 if stale else math.nan, reference_price * 0.99]
        sar_down = [math.nan if stale else reference_price * 1.01, math.nan]
    else:
        sar_up = [math.nan if stale else reference_price * 0.99, math.nan]
        sar_down = [
            reference_price * 1.01 if stale else math.nan,
            reference_price * 1.01,
        ]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [reference_price, reference_price],
            "high": [reference_price * 1.001, reference_price * 1.001],
            "low": [reference_price * 0.999, reference_price * 0.999],
            "close": [reference_price, reference_price],
            "volume": [1.0, 1.0],
            "sar_up": sar_up,
            "sar_down": sar_down,
        }
    )


async def _run_signal(
    app: ModuleType,
    *,
    symbol: str,
    end: datetime,
    direction: str,
    stale: bool = False,
) -> None:
    price = await app.hyperliquid_exchange.fetch_last_price(symbol)
    frame = _controlled_frame(
        end,
        direction=direction,
        reference_price=price,
        stale=stale,
    )
    await app.check_signal(
        startDate=end - timedelta(days=1),
        endDate=end,
        symbol=symbol,
        timeframe=TIMEFRAME,
        amountByUSDC=ORDER_NOTIONAL_USDC,
        controlled_dataframe=frame,
    )


def _intent_summary(database_path: Path) -> dict[str, Any]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT strategy, reduce_only, status FROM order_intents ORDER BY updated_at"
        ).fetchall()
    return {
        "total": len(rows),
        "entries": sum(1 for _, reduce_only, _ in rows if not reduce_only),
        "closes": sum(1 for _, reduce_only, _ in rows if reduce_only),
        "filled": sum(1 for _, _, status in rows if status == "filled"),
        "unsettled": sum(
            1
            for _, _, status in rows
            if status not in {"filled", "cancelled", "rejected"}
        ),
        "strategies": sorted({str(strategy) for strategy, _, _ in rows}),
    }


async def _graceful_close(app: ModuleType) -> None:
    supervisor = RuntimeSupervisor(
        resources=[app.runtime_state, app.hyperliquid_exchange],
        on_shutdown_requested=app.order_executor.stop_accepting,
    )

    async def wait_for_shutdown() -> None:
        await supervisor.shutdown_event.wait()

    running = asyncio.create_task(supervisor.run([wait_for_shutdown()]))
    await asyncio.sleep(0)
    supervisor.request_shutdown()
    await running


async def _restart(
    app: ModuleType,
    secrets_path: Path,
    settings_path: Path,
    state_path: Path,
) -> ModuleType:
    await _graceful_close(app)
    restarted = _load_production_app(secrets_path, settings_path, state_path)
    recovered = await restarted.order_executor.recover_unsettled()
    if any(
        intent.status.value not in {"filled", "cancelled", "rejected"}
        for intent in recovered
    ):
        raise RuntimeError("restart left an unresolved order intent")
    await restarted.initialize_trailing_manager()
    restarted.runtime_state.health.write("running")
    return restarted


async def _verify_trailing_restart(
    app: ModuleType,
    *,
    symbol: str,
    trailing: dict[str, Any],
    secrets_path: Path,
    settings_path: Path,
    state_path: Path,
) -> ModuleType:
    stop_before_restart = float(trailing["stop_after"])
    trailing_side = str(trailing["side"])
    restarted = await _restart(app, secrets_path, settings_path, state_path)
    await restarted.protection_reconciler.reconcile_symbol(symbol)
    recovered = await restarted.hyperliquid_exchange.fetch_tp_sl_info(symbol)
    if recovered is None:
        raise RuntimeError("protection missing after trailing restart")
    recovered_stop = float(recovered.stop_loss_trigger_price)
    non_retreat = (
        trailing_side == "long" and recovered_stop >= stop_before_restart
    ) or (trailing_side == "short" and recovered_stop <= stop_before_restart)
    if not non_retreat:
        raise RuntimeError("trailing stop retreated after restart")
    return restarted


async def _force_websocket_reconnect(app: ModuleType, symbol: str) -> dict[str, Any]:
    client = app.hyperliquid_exchange.ws_client
    coin = symbol.split("/")[0]
    messages = 0

    def on_trade(_message: dict[str, Any]) -> None:
        nonlocal messages
        messages += 1

    await client.connect()
    await client.subscribe_trade(coin, on_trade)
    listener = asyncio.create_task(client.listen())
    try:
        await asyncio.sleep(1)
        if client.ws is None:
            raise RuntimeError("WebSocket missing before forced disconnect")
        started = time.monotonic()
        await client.ws.close()
        deadline = started + 30
        while time.monotonic() < deadline and client.reconnect_count < 1:
            await asyncio.sleep(0.25)
        if client.reconnect_count < 1:
            raise TimeoutError("WebSocket did not reconnect")
        return {
            "forced_reconnect_seconds": round(time.monotonic() - started, 3),
            "reconnect_count": client.reconnect_count,
            "trade_messages": messages,
        }
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)


async def _exercise_trailing(
    app: ModuleType,
    symbol: str,
    *,
    timeout: float,
    sample_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    previous_sample = started
    samples = 0
    unprotected_seconds = 0.0
    while time.monotonic() - started < timeout:
        position = _active_position(
            list(await app.hyperliquid_exchange.fetch_positions()), symbol
        )
        if position is None:
            raise RuntimeError("position disappeared while testing trailing protection")
        orders = list(await app.hyperliquid_exchange.fetch_open_orders(symbol))
        now = time.monotonic()
        if sum(1 for order in orders if _is_protection(order)) < 2:
            unprotected_seconds += now - previous_sample
            await app.protection_reconciler.reconcile_symbol(symbol)
        samples += 1
        previous_sample = now
        side = str(position.get("side"))
        entry = float(position.get("entryPrice") or 0)
        last = await app.hyperliquid_exchange.fetch_last_price(symbol)
        favorable = (side == "long" and last > entry) or (
            side == "short" and last < entry
        )
        favorable_distance = abs(last - entry) / entry
        if favorable and favorable_distance >= 0.0002:
            manager_position = app.trailing_manager.get_position(symbol)
            if manager_position is None:
                raise RuntimeError("production trailing manager did not adopt position")
            initial_stop = float(manager_position.current_stoploss_price)
            app.trailing_manager.activate_trailing(symbol, entry)
            desired_stop = float(manager_position.current_stoploss_price)
            if side == "long" and not desired_stop >= entry:
                await asyncio.sleep(sample_seconds)
                continue
            if side == "short" and not desired_stop <= entry:
                await asyncio.sleep(sample_seconds)
                continue
            await app.protection_reconciler.reconcile_symbol(
                symbol, trailing_stop=desired_stop
            )
            actual = await app.hyperliquid_exchange.fetch_tp_sl_info(symbol)
            if actual is None:
                # Hyperliquid can briefly expose only one side after the new SL
                # is verified and the old SL is cancelled. Retry the full
                # reconciliation instead of treating that short view as truth.
                await asyncio.sleep(1)
                await app.protection_reconciler.reconcile_symbol(
                    symbol, trailing_stop=desired_stop
                )
                actual = await app.hyperliquid_exchange.fetch_tp_sl_info(symbol)
            if actual is None:
                raise RuntimeError("trailing update did not converge to a TP/SL pair")
            actual_stop = float(actual.stop_loss_trigger_price)
            breakeven_reached = (side == "long" and actual_stop >= entry) or (
                side == "short" and actual_stop <= entry
            )
            moved_to_profit = (side == "long" and actual_stop > initial_stop) or (
                side == "short" and actual_stop < initial_stop
            )
            if not moved_to_profit:
                await asyncio.sleep(sample_seconds)
                continue
            return {
                "activated": True,
                "side": side,
                "samples": samples,
                "wait_seconds": round(time.monotonic() - started, 2),
                "unprotected_seconds": round(unprotected_seconds, 3),
                "breakeven_reached": breakeven_reached,
                "profit_direction_update": True,
                "stop_before": initial_stop,
                "stop_after": actual_stop,
            }
        print(
            json.dumps(
                {
                    "event": "await_favorable_testnet_price",
                    "side": side,
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                    "samples": samples,
                }
            ),
            flush=True,
        )
        await asyncio.sleep(sample_seconds)
    return {
        "activated": False,
        "samples": samples,
        "wait_seconds": round(time.monotonic() - started, 2),
        "unprotected_seconds": round(unprotected_seconds, 3),
    }


async def _manual_close(app: ModuleType, symbol: str) -> None:
    position = _active_position(
        list(await app.hyperliquid_exchange.fetch_positions()), symbol
    )
    if position is None:
        return
    side = "sell" if position.get("side") == "long" else "buy"
    amount = abs(float(position.get("contracts") or 0))
    prepared = await app.hyperliquid_exchange.prepare_market_order(symbol, amount)
    manual_intent = create_intent(
        strategy="testnet-external-manual-close-v1",
        symbol=symbol,
        side=side,
        amount=prepared.amount,
        timeframe="manual",
        candle_open_ms=int(time.time() * 1000),
        reduce_only=True,
    )
    await app.hyperliquid_exchange.submit_market_order(manual_intent)
    await _wait_for_position(app.hyperliquid_exchange, symbol, None)
    await app.protection_reconciler.reconcile_symbol(symbol)


async def run(
    monitor_seconds: int, sample_seconds: float, initial_side: str
) -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    if os.getenv("HYPERLIQUID_TESTNET", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("HYPERLIQUID_TESTNET=true is required")
    wallet = os.environ["HYPERLIQUID_WALLET_ADDRESS"]
    private_key = os.environ["HYPERLIQUID_PRIVATE_KEY"]
    started_monotonic = time.monotonic()
    report: dict[str, Any] = {
        "network": "testnet",
        "started_at": _utc_now(),
        "mainnet_operations": 0,
        "unresolved_errors": [],
    }
    opposite_side = "short" if initial_side == "long" else "long"
    symbol, initial_positions = await _select_flat_symbol(wallet, private_key)
    report["symbol"] = symbol
    report["preexisting_position_count"] = len(initial_positions)

    with tempfile.TemporaryDirectory(
        prefix="hyperliquid-production-e2e-", ignore_cleanup_errors=True
    ) as raw_dir:
        directory = Path(raw_dir)
        secrets_path, settings_path, state_path = _write_runtime_files(
            directory,
            wallet=wallet,
            private_key=private_key,
            symbol=symbol,
        )
        app: ModuleType | None = None
        sequence_end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        try:
            app = _load_production_app(secrets_path, settings_path, state_path)
            await app.protection_reconciler.reconcile_symbol(symbol)
            app.runtime_state.health.write("running")

            await _run_signal(
                app,
                symbol=symbol,
                end=sequence_end,
                direction=initial_side,
                stale=True,
            )
            if (
                _active_position(
                    list(await app.hyperliquid_exchange.fetch_positions()), symbol
                )
                is not None
            ):
                raise RuntimeError("stale SAR interval unexpectedly opened a position")
            report["stale_sar_rejected"] = True

            sequence_end += timedelta(minutes=1)
            await _run_signal(
                app, symbol=symbol, end=sequence_end, direction=initial_side
            )
            first_position = await _wait_for_position(
                app.hyperliquid_exchange, symbol, initial_side
            )
            assert first_position is not None
            first_orders = list(
                await app.hyperliquid_exchange.fetch_open_orders(symbol)
            )
            if sum(1 for order in first_orders if _is_protection(order)) != 2:
                raise RuntimeError(
                    f"{initial_side} entry was not protected by exactly TP and SL"
                )
            intent_count = _intent_summary(app.runtime_state.database_path)["total"]
            await _run_signal(
                app, symbol=symbol, end=sequence_end, direction=initial_side
            )
            if (
                _intent_summary(app.runtime_state.database_path)["total"]
                != intent_count
            ):
                raise RuntimeError("duplicate candle created another intent")
            report[f"{initial_side}_entry"] = {
                "confirmed": True,
                "contracts": abs(float(first_position.get("contracts") or 0)),
                "protection_orders": 2,
                "duplicate_candle_intents_added": 0,
            }

            app = await _restart(app, secrets_path, settings_path, state_path)
            await _run_signal(
                app, symbol=symbol, end=sequence_end, direction=initial_side
            )
            if (
                _intent_summary(app.runtime_state.database_path)["total"]
                != intent_count
            ):
                raise RuntimeError("restart replay created another intent")
            report["restart_recovery"] = {
                "durable_intent_replay_added": 0,
                "position_restored": app.trailing_manager.get_position(symbol)
                is not None,
                "protection_orders": sum(
                    1
                    for order in await app.hyperliquid_exchange.fetch_open_orders(
                        symbol
                    )
                    if _is_protection(order)
                ),
            }
            report["websocket"] = await _force_websocket_reconnect(app, symbol)

            first_budget = max(1, monitor_seconds // 2)
            trailing = await _exercise_trailing(
                app,
                symbol,
                timeout=first_budget,
                sample_seconds=sample_seconds,
            )
            if trailing.get("activated"):
                app = await _verify_trailing_restart(
                    app,
                    symbol=symbol,
                    trailing=trailing,
                    secrets_path=secrets_path,
                    settings_path=settings_path,
                    state_path=state_path,
                )
                report["trailing_restart_non_retreat"] = True

            sequence_end += timedelta(minutes=1)
            await _run_signal(
                app, symbol=symbol, end=sequence_end, direction=opposite_side
            )
            await _wait_for_position(app.hyperliquid_exchange, symbol, None)
            report["opposite_sar_close"] = {
                "reduce_only": True,
                "flat_confirmed_before_reverse": True,
            }

            sequence_end += timedelta(minutes=1)
            await _run_signal(
                app, symbol=symbol, end=sequence_end, direction=opposite_side
            )
            second_position = await _wait_for_position(
                app.hyperliquid_exchange, symbol, opposite_side
            )
            assert second_position is not None
            second_orders = list(
                await app.hyperliquid_exchange.fetch_open_orders(symbol)
            )
            if sum(1 for order in second_orders if _is_protection(order)) != 2:
                raise RuntimeError(
                    f"{opposite_side} entry was not protected by exactly TP and SL"
                )
            report[f"{opposite_side}_entry"] = {
                "confirmed": True,
                "contracts": abs(float(second_position.get("contracts") or 0)),
                "protection_orders": 2,
            }

            if not trailing.get("activated"):
                trailing = await _exercise_trailing(
                    app,
                    symbol,
                    timeout=max(1, monitor_seconds - first_budget),
                    sample_seconds=sample_seconds,
                )
                if trailing.get("activated"):
                    app = await _verify_trailing_restart(
                        app,
                        symbol=symbol,
                        trailing=trailing,
                        secrets_path=secrets_path,
                        settings_path=settings_path,
                        state_path=state_path,
                    )
                    report["trailing_restart_non_retreat"] = True
            if not trailing.get("activated"):
                raise RuntimeError(
                    "testnet price never allowed a safe trailing activation"
                )
            report["trailing"] = trailing

            await _manual_close(app, symbol)
            report["manual_settlement_reconciled"] = True
            final_positions = list(await app.hyperliquid_exchange.fetch_positions())
            final_orders = list(await app.hyperliquid_exchange.fetch_open_orders(None))
            active_final_positions = [
                position
                for position in final_positions
                if abs(float(position.get("contracts") or 0)) > 0
            ]
            report["final"] = {
                "account_active_positions": len(active_final_positions),
                "account_open_orders": len(final_orders),
            }
            report["intents"] = _intent_summary(app.runtime_state.database_path)
            if report["intents"]["unsettled"]:
                raise RuntimeError("durable order intents remain unsettled")
            if active_final_positions or final_orders:
                raise RuntimeError("acceptance cleanup did not leave the account clean")
        except Exception as exc:
            report["unresolved_errors"].append(type(exc).__name__)
            raise
        finally:
            if app is not None:
                try:
                    await _manual_close(app, symbol)
                except Exception as cleanup_error:
                    report["cleanup_error"] = type(cleanup_error).__name__
                try:
                    await _graceful_close(app)
                    report["graceful_shutdown"] = True
                except Exception as shutdown_error:
                    report["shutdown_error"] = type(shutdown_error).__name__

    report["ended_at"] = _utc_now()
    report["runtime_seconds"] = round(time.monotonic() - started_monotonic, 2)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor-seconds", type=int, default=600)
    parser.add_argument("--sample-seconds", type=float, default=5.0)
    parser.add_argument("--initial-side", choices=("long", "short"), default="long")
    args = parser.parse_args()
    if args.monitor_seconds <= 0 or args.sample_seconds <= 0:
        parser.error("durations must be positive")
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="INFO")
    result = asyncio.run(
        run(args.monitor_seconds, args.sample_seconds, args.initial_side)
    )
    print("ACCEPTANCE_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
