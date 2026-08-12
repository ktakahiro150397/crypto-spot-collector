"""Run a destructive-but-contained HyperLiquid testnet acceptance scenario.

The scenario opens one small position on a symbol that was flat at startup,
verifies durable order idempotency and exchange-truth TP/SL reconciliation,
forces a WebSocket reconnect, monitors the protected position, then proves a
long -> flat -> short -> flat transition. It never selects mainnet and cleans
up only the symbol it selected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv
from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.trading.config import TradingConfig
from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderIntent,
    OrderStatus,
    SQLiteOrderIntentStore,
    create_intent,
)
from crypto_spot_collector.trading.protection import ProtectionReconciler

SYMBOL_CANDIDATES = (
    "BTC/USDC:USDC",
    "SOL/USDC:USDC",
    "HYPE/USDC:USDC",
    "AVAX/USDC:USDC",
)
LEVERAGE = 3
TAKE_PROFIT_ROE = 0.15
STOP_LOSS_ROE = 0.03


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
    order_type = str(
        order.get("info", {}).get("orderType") or order.get("type") or ""
    ).lower()
    return "take profit" in order_type or "stop" in order_type


def _protection_count(orders: list[dict[str, Any]]) -> int:
    return sum(1 for order in orders if _is_protection(order))


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
        await asyncio.sleep(1)
    raise TimeoutError(f"position did not become {expected_side or 'flat'}: {symbol}")


async def _wait_until(
    predicate: Callable[[], Awaitable[bool]], *, timeout: float = 30.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.25)
    raise TimeoutError("acceptance condition was not reached")


async def _create_and_execute(
    executor: IdempotentOrderExecutor,
    *,
    symbol: str,
    side: str,
    amount: float,
    reduce_only: bool,
    sequence: int,
) -> tuple[OrderIntent, OrderIntent]:
    requested = create_intent(
        strategy="hyperliquid-testnet-acceptance",
        symbol=symbol,
        timeframe="acceptance",
        candle_open_ms=sequence,
        side=side,
        amount=amount,
        reduce_only=reduce_only,
    )
    first = await executor.execute(requested)
    second = await executor.execute(requested)
    if first.status is not OrderStatus.FILLED:
        raise RuntimeError(f"testnet order did not fill: {first.status.value}")
    if second.intent_id != first.intent_id or second.order_id != first.order_id:
        raise RuntimeError("duplicate intent did not resolve to the original order")
    return first, second


async def _close_selected_symbol(
    exchange: HyperLiquidExchange,
    executor: IdempotentOrderExecutor,
    symbol: str,
    sequence: int,
) -> OrderIntent | None:
    position = _active_position(list(await exchange.fetch_positions()), symbol)
    if position is None:
        return None
    side = "sell" if position.get("side") == "long" else "buy"
    amount = abs(float(position.get("contracts") or 0))
    result, _ = await _create_and_execute(
        executor,
        symbol=symbol,
        side=side,
        amount=amount,
        reduce_only=True,
        sequence=sequence,
    )
    await _wait_for_position(exchange, symbol, None)
    return result


async def run(monitor_seconds: int, sample_seconds: int) -> dict[str, Any]:
    load_dotenv(Path.cwd() / ".env")
    if os.getenv("HYPERLIQUID_TESTNET", "").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("HYPERLIQUID_TESTNET=true is required")
    wallet = os.environ["HYPERLIQUID_WALLET_ADDRESS"]
    private_key = os.environ["HYPERLIQUID_PRIVATE_KEY"]
    started_at = _utc_now()
    started_sequence = int(time.time() * 1000)
    report: dict[str, Any] = {
        "network": "testnet",
        "started_at": started_at,
        "monitor_requested_seconds": monitor_seconds,
        "sample_seconds": sample_seconds,
    }
    trading_config = TradingConfig(
        symbols=SYMBOL_CANDIDATES,
        timeframe="1m",
        amount_usdc=12.5,
        leverage=LEVERAGE,
        take_profit_roe=TAKE_PROFIT_ROE,
        stop_loss_roe=STOP_LOSS_ROE,
        trailing_interval_minutes=1,
        trailing_activation_roe=1.0,
        sar_consecutive_count=1,
        sar_close_consecutive_count=1,
        price_change_threshold_percent=1.0,
    )

    exchange = HyperLiquidExchange(
        mainWalletAddress=wallet,
        apiWalletAddress=wallet,
        privateKey=private_key,
        trading_config=trading_config,
    )
    reconciler = ProtectionReconciler(
        exchange,
        take_profit_roe=TAKE_PROFIT_ROE,
        stop_loss_roe=STOP_LOSS_ROE,
        leverage=LEVERAGE,
    )
    listener: asyncio.Task[None] | None = None

    with tempfile.TemporaryDirectory(prefix="hyperliquid-acceptance-") as state_dir:
        store = SQLiteOrderIntentStore(Path(state_dir) / "order-intents.sqlite")
        executor = IdempotentOrderExecutor(exchange, store)
        selected_symbol: str | None = None
        try:
            positions = list(await exchange.fetch_positions())
            initial_positions = {
                str(position.get("symbol")): {
                    "side": position.get("side"),
                    "contracts": float(position.get("contracts") or 0),
                    "leverage": float(position.get("leverage") or 0),
                }
                for position in positions
                if abs(float(position.get("contracts") or 0)) > 0
            }
            report["preexisting_positions"] = initial_positions
            selected_symbol = next(
                (
                    symbol
                    for symbol in SYMBOL_CANDIDATES
                    if _active_position(positions, symbol) is None
                ),
                None,
            )
            if selected_symbol is None:
                raise RuntimeError("no configured acceptance symbol is flat")
            report["symbol"] = selected_symbol

            await exchange.exchange_private.load_markets()
            await exchange.exchange_private.set_leverage(
                LEVERAGE, selected_symbol, {"marginMode": "cross"}
            )
            # Remove only stale protections on the selected, initially-flat symbol.
            await reconciler.reconcile_symbol(selected_symbol)
            price = await exchange.fetch_last_price(selected_symbol)
            market = exchange.exchange_private.market(selected_symbol)
            minimum_cost = float(
                (market.get("limits", {}).get("cost", {}) or {}).get("min") or 10
            )
            notional = max(12.5, minimum_cost * 1.25)
            raw_amount = notional / price
            amount = float(
                exchange.exchange_private.amount_to_precision(
                    selected_symbol, raw_amount
                )
            )
            if amount <= 0 or amount * price < minimum_cost:
                raise RuntimeError(
                    "could not construct an order above the market minimum"
                )
            report["test_notional_usdc"] = round(amount * price, 4)

            long_entry, long_duplicate = await _create_and_execute(
                executor,
                symbol=selected_symbol,
                side="buy",
                amount=amount,
                reduce_only=False,
                sequence=started_sequence,
            )
            long_position = await _wait_for_position(exchange, selected_symbol, "long")
            long_protection = await reconciler.reconcile_symbol(selected_symbol)
            report["long_entry"] = {
                "status": long_entry.status.value,
                "duplicate_resolved_to_same_order": (
                    long_duplicate.order_id == long_entry.order_id
                ),
                "position_contracts": float(long_position.get("contracts") or 0),
                "protection_created": len(long_protection.created),
            }

            reconnect_callbacks = 0

            async def on_reconnect() -> None:
                nonlocal reconnect_callbacks
                reconnect_callbacks += 1
                await reconciler.reconcile_symbol(selected_symbol)

            exchange.ws_client.set_reconnect_callback(on_reconnect)
            trade_messages = 0

            def on_trade(_: dict[str, Any]) -> None:
                nonlocal trade_messages
                trade_messages += 1

            coin = selected_symbol.split("/")[0]
            await exchange.ws_client.connect()
            await exchange.ws_client.subscribe_trade(coin, on_trade)
            listener = asyncio.create_task(exchange.ws_client.listen())
            await asyncio.sleep(2)
            if exchange.ws_client.ws is None:
                raise RuntimeError("WebSocket missing before forced disconnect")
            reconnect_started = time.monotonic()
            await exchange.ws_client.ws.close()

            async def reconnected() -> bool:
                return (
                    exchange.ws_client.reconnect_count >= 1 and reconnect_callbacks >= 1
                )

            await _wait_until(reconnected, timeout=30)
            report["websocket"] = {
                "forced_reconnect_seconds": round(
                    time.monotonic() - reconnect_started, 3
                ),
                "reconnect_count": exchange.ws_client.reconnect_count,
                "reconcile_callbacks": reconnect_callbacks,
            }

            samples = 0
            unprotected_seconds = 0.0
            monitor_started = time.monotonic()
            previous_sample = monitor_started
            while time.monotonic() - monitor_started < monitor_seconds:
                positions = list(await exchange.fetch_positions())
                position = _active_position(positions, selected_symbol)
                orders = list(await exchange.fetch_open_orders(selected_symbol))
                now = time.monotonic()
                if position is None:
                    raise RuntimeError("monitored long position disappeared")
                if _protection_count(orders) < 2:
                    unprotected_seconds += now - previous_sample
                    await reconciler.reconcile_symbol(selected_symbol)
                samples += 1
                previous_sample = now
                elapsed = round(now - monitor_started, 1)
                print(
                    json.dumps(
                        {
                            "event": "monitor",
                            "elapsed_seconds": elapsed,
                            "samples": samples,
                        }
                    )
                )
                remaining = monitor_seconds - (now - monitor_started)
                if remaining > 0:
                    await asyncio.sleep(min(sample_seconds, remaining))
            report["monitor"] = {
                "actual_seconds": round(time.monotonic() - monitor_started, 2),
                "samples": samples,
                "unprotected_seconds": round(unprotected_seconds, 3),
                "trade_messages": trade_messages,
            }
            report["websocket"][
                "reconnect_count_final"
            ] = exchange.ws_client.reconnect_count
            report["websocket"]["reconcile_callbacks_final"] = reconnect_callbacks

            long_close = await _close_selected_symbol(
                exchange, executor, selected_symbol, started_sequence + 1
            )
            flat_report = await reconciler.reconcile_symbol(selected_symbol)
            report["long_close"] = {
                "status": long_close.status.value if long_close else "already_flat",
                "orphan_orders_cancelled": flat_report.orphan_count,
            }

            short_entry, short_duplicate = await _create_and_execute(
                executor,
                symbol=selected_symbol,
                side="sell",
                amount=amount,
                reduce_only=False,
                sequence=started_sequence + 2,
            )
            short_position = await _wait_for_position(
                exchange, selected_symbol, "short"
            )
            short_protection = await reconciler.reconcile_symbol(selected_symbol)
            report["short_entry"] = {
                "status": short_entry.status.value,
                "duplicate_resolved_to_same_order": (
                    short_duplicate.order_id == short_entry.order_id
                ),
                "position_contracts": float(short_position.get("contracts") or 0),
                "protection_created": len(short_protection.created),
            }
            await asyncio.sleep(5)
            short_close = await _close_selected_symbol(
                exchange, executor, selected_symbol, started_sequence + 3
            )
            final_reconcile = await reconciler.reconcile_symbol(selected_symbol)
            final_orders = list(await exchange.fetch_open_orders(selected_symbol))
            report["short_close"] = {
                "status": short_close.status.value if short_close else "already_flat",
                "orphan_orders_cancelled": final_reconcile.orphan_count,
            }
            report["final"] = {
                "selected_symbol_flat": _active_position(
                    list(await exchange.fetch_positions()), selected_symbol
                )
                is None,
                "selected_symbol_open_orders": len(final_orders),
            }
        finally:
            if selected_symbol is not None:
                try:
                    await _close_selected_symbol(
                        exchange, executor, selected_symbol, started_sequence + 99
                    )
                    await reconciler.reconcile_symbol(selected_symbol)
                except Exception as cleanup_error:
                    report["cleanup_error"] = type(cleanup_error).__name__
            if listener is not None:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)
            await exchange.close()

    report["ended_at"] = _utc_now()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monitor-seconds", type=int, default=600)
    parser.add_argument("--sample-seconds", type=int, default=10)
    args = parser.parse_args()
    if args.monitor_seconds < 0 or args.sample_seconds <= 0:
        parser.error("durations must be positive")
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="INFO")
    result = asyncio.run(run(args.monitor_seconds, args.sample_seconds))
    print("ACCEPTANCE_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
