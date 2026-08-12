import math
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Callable, Optional

import ccxt.async_support as ccxt_async
from loguru import logger

from crypto_spot_collector.exchange.hyperliquid_ws import HyperLiquidWebSocket
from crypto_spot_collector.exchange.interface import IExchange
from crypto_spot_collector.exchange.types import (
    PositionSide,
    SpotAsset,
    SpotOrderResult,
)
from crypto_spot_collector.trading.config import TradingConfig
from crypto_spot_collector.trading.order_state import OrderIntent
from crypto_spot_collector.trading.protection import ProtectionSpec
from crypto_spot_collector.trading.resilience import (
    IDEMPOTENT_WRITE_POLICY,
    WRITE_POLICY,
    ResilientCaller,
)


class HyperLiquidPerpOnlyTestnet(ccxt_async.hyperliquid):
    """Work around malformed testnet spot metadata without hiding perp markets."""

    async def fetch_markets(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return list(await self.fetch_swap_markets(params or {}))


@dataclass
class HyperliquidTakeProfitStopLossPositionInfo:
    symbol: str
    take_profit_order_id: str
    stop_loss_order_id: str
    take_profit_trigger_price: float
    stop_loss_trigger_price: float


@dataclass(frozen=True)
class PreparedMarketOrder:
    amount: float
    reference_price: float


class HyperLiquidExchange(IExchange):
    def __init__(
        self,
        mainWalletAddress: str,
        apiWalletAddress: str,
        privateKey: str,
        trading_config: TradingConfig,
    ) -> None:
        """Create the adapter only from a fully validated runtime config.

        Keeping network selection at this boundary prevents scripts from
        bypassing the mainnet interlock with a raw ``testnet=False`` flag.
        """
        trading_config.validate()
        testnet = trading_config.testnet
        logger.info("Initializing HyperLiquid exchange client")
        if privateKey and not privateKey.startswith("0x"):
            privateKey = "0x" + privateKey
        exchange_type = (
            HyperLiquidPerpOnlyTestnet if testnet else ccxt_async.hyperliquid
        )
        self.exchange_public = exchange_type(
            {
                "walletAddress": mainWalletAddress,
            }
        )

        self.exchange_private = exchange_type(
            {
                "walletAddress": apiWalletAddress,
                "privateKey": privateKey,
            }
        )

        if testnet:
            self.exchange_public.set_sandbox_mode(True)
            self.exchange_private.set_sandbox_mode(True)
            logger.info("HyperLiquid exchange set to testnet mode")

        self.trading_config = trading_config
        self.take_profit_rate = trading_config.take_profit_roe
        self.stop_loss_rate = trading_config.stop_loss_roe
        self.leverage = trading_config.leverage
        self.rest = ResilientCaller(requests_per_second=10.0)

        # WebSocketクライアントの初期化
        self.ws_client = HyperLiquidWebSocket(testnet=testnet)

        logger.info(
            f"HyperLiquid exchange client initialized successfully. "
            f"Take Profit ROE: {self.take_profit_rate:.2f}%, "
            f"Stop Loss ROE: {self.stop_loss_rate:.2f}%, "
            f"Leverage: x{self.leverage}, "
            f"Network: {'testnet' if testnet else 'mainnet'}"
        )

    async def __aenter__(self) -> "IExchange":
        """Async context manager entry"""
        logger.debug("Entering HyperLiquidExchange async context")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        """Async context manager exit - automatically closes resources"""
        logger.debug("Exiting HyperLiquidExchange async context")
        await self.close()
        return False

    async def close(self) -> None:
        """Explicitly close all exchange connections"""
        logger.info("Closing HyperLiquid exchange connections")
        if hasattr(self, "exchange_public") and self.exchange_public:
            await self.exchange_public.close()
            logger.debug("Public exchange connection closed")
        if hasattr(self, "exchange_private") and self.exchange_private:
            await self.exchange_private.close()
            logger.debug("Private exchange connection closed")
        if hasattr(self, "ws_client") and self.ws_client:
            await self.ws_client.disconnect()
            logger.debug("WebSocket connection closed")
        logger.info("All HyperLiquid exchange connections closed successfully")

    async def fetch_balance_async(self) -> Any:
        logger.debug("Fetching account balance asynchronously")
        balance = await self.rest.call(
            "fetch_balance", lambda: self.exchange_public.fetch_balance()
        )
        logger.debug("Account balance fetched successfully (async)")
        return balance

    async def fetch_free_usdt_async(self) -> float:
        logger.debug("Fetching free USDT balance asynchronously")
        balance = await self.fetch_balance_async()

        free_usdt = balance["free"]["USDC"]
        return float(free_usdt)

    async def fetch_free_collateral(self) -> float:
        """Return free USDC collateral for the entry risk gate."""

        return await self.fetch_free_usdt_async()

    async def fetch_price_async(self, symbol: str) -> dict[Any, Any]:
        logger.debug(f"Fetching price for {symbol} asynchronously")
        ticker: dict[Any, Any] = await self.rest.call(
            "fetch_ticker", lambda: self.exchange_public.fetch_ticker(symbol)
        )
        if "last" in ticker:
            logger.debug(f"Price for {symbol}: {ticker['last']} (async)")
        else:
            logger.error(f"Price not found for symbol {symbol}")
            raise Exception(f"symbol = {symbol} | Price not found in ticker data")
        return ticker

    async def fetch_last_price(self, symbol: str) -> float:
        """Return the latest traded price for protection safety checks."""
        ticker = await self.fetch_price_async(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)

    async def submit_market_order(self, intent: OrderIntent) -> dict[str, Any]:
        """Submit an intent using its deterministic Hyperliquid cloid."""
        ticker = await self.fetch_price_async(intent.symbol)
        market_price = float(ticker["last"])
        prepared = await self.prepare_market_order(
            intent.symbol,
            intent.amount,
            reference_price=market_price,
        )
        if not math.isclose(prepared.amount, intent.amount, rel_tol=1e-12):
            raise ValueError(
                f"intent amount {intent.amount} is not normalized for "
                f"{intent.symbol}; expected {prepared.amount}"
            )
        if not intent.reduce_only:
            await self.ensure_market_configuration(intent.symbol)
        params: dict[str, Any] = {
            "clientOrderId": intent.cloid,
            "reduceOnly": intent.reduce_only,
        }
        result = await self.rest.call(
            "submit_market_order",
            lambda: self.exchange_private.create_order(
                symbol=intent.symbol,
                type="market",
                side=intent.side,
                amount=intent.amount,
                price=prepared.reference_price,
                params=params,
            ),
            policy=WRITE_POLICY,
        )
        return dict(result)

    async def prepare_market_order(
        self,
        symbol: str,
        amount: float,
        *,
        reference_price: float | None = None,
    ) -> PreparedMarketOrder:
        """Normalize amount/price and enforce exchange market limits."""

        await self.rest.call(
            "load_markets",
            lambda: self.exchange_private.load_markets(),
        )
        market = self.exchange_private.market(symbol)
        if reference_price is None:
            reference_price = await self.fetch_last_price(symbol)
        reference_price = float(reference_price)
        if not math.isfinite(reference_price) or reference_price <= 0:
            raise ValueError(f"invalid reference price for {symbol}")
        requested_amount = abs(float(amount))
        if not math.isfinite(requested_amount) or requested_amount <= 0:
            raise ValueError(f"invalid order amount for {symbol}")
        normalized_amount = float(
            self.exchange_private.amount_to_precision(symbol, requested_amount)
        )
        normalized_price = float(
            self.exchange_private.price_to_precision(symbol, reference_price)
        )
        if (
            not math.isfinite(normalized_amount)
            or not math.isfinite(normalized_price)
            or normalized_amount <= 0
            or normalized_price <= 0
        ):
            raise ValueError(f"order for {symbol} rounds to zero")

        limits = market.get("limits", {})
        minimum_amount = float((limits.get("amount", {}) or {}).get("min") or 0)
        # Hyperliquid's documented perp minimum is $10. Prefer stricter live
        # metadata when CCXT exposes one.
        minimum_cost = max(
            10.0,
            float((limits.get("cost", {}) or {}).get("min") or 0),
        )
        notional = normalized_amount * normalized_price
        if minimum_amount and normalized_amount < minimum_amount:
            raise ValueError(
                f"order amount {normalized_amount} is below {symbol} minimum "
                f"{minimum_amount}"
            )
        if notional < minimum_cost:
            raise ValueError(
                f"order notional {notional:.8f} is below {symbol} minimum "
                f"{minimum_cost:.8f}"
            )
        return PreparedMarketOrder(
            amount=normalized_amount,
            reference_price=normalized_price,
        )

    async def ensure_market_configuration(self, symbol: str) -> None:
        """Set and verify the configured leverage/margin mode before entry."""

        await self.rest.call(
            "load_markets",
            lambda: self.exchange_private.load_markets(),
        )
        market = self.exchange_private.market(symbol)
        leverage_limits = market.get("limits", {}).get("leverage", {}) or {}
        market_max_leverage = float(
            leverage_limits.get("max") or market.get("info", {}).get("maxLeverage") or 0
        )
        if market_max_leverage and self.leverage > market_max_leverage:
            raise ValueError(
                f"configured leverage {self.leverage} exceeds {symbol} maximum "
                f"{market_max_leverage:g}"
            )
        response = await self.rest.call(
            "set_leverage",
            lambda: self.exchange_private.set_leverage(
                self.leverage,
                symbol,
                {"marginMode": self.trading_config.margin_mode},
            ),
            policy=WRITE_POLICY,
        )
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise RuntimeError(
                f"exchange did not acknowledge leverage/margin mode for {symbol}"
            )

    async def fetch_order_by_cloid(
        self, symbol: str, cloid: str
    ) -> dict[str, Any] | None:
        try:
            order = await self.rest.call(
                "fetch_order",
                lambda: self.exchange_public.fetch_order(
                    cloid, symbol, {"clientOrderId": cloid}
                ),
            )
        except ccxt_async.OrderNotFound:
            return None
        return dict(order)

    async def fetch_open_orders(
        self, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        return list(
            await self.rest.call(
                "fetch_open_orders",
                lambda: self.exchange_public.fetch_open_orders(symbol),
            )
        )

    async def fetch_fills(self, symbol: str) -> list[dict[str, Any]]:
        return list(
            await self.rest.call(
                "fetch_fills", lambda: self.exchange_public.fetch_my_trades(symbol)
            )
        )

    async def fetch_positions(self) -> list[dict[str, Any]]:
        return list(
            await self.rest.call(
                "fetch_positions", lambda: self.exchange_public.fetch_positions()
            )
        )

    async def create_protection_order(self, spec: ProtectionSpec) -> dict[str, Any]:
        await self.rest.call(
            "load_markets",
            lambda: self.exchange_private.load_markets(),
        )
        normalized_amount = float(
            self.exchange_private.amount_to_precision(spec.symbol, spec.amount)
        )
        normalized_trigger = float(
            self.exchange_private.price_to_precision(spec.symbol, spec.trigger_price)
        )
        if (
            not math.isfinite(normalized_amount)
            or not math.isfinite(normalized_trigger)
            or normalized_amount <= 0
            or normalized_trigger <= 0
        ):
            raise ValueError(f"protection order for {spec.symbol} rounds to zero")
        price_key = "takeProfitPrice" if spec.kind == "take_profit" else "stopLossPrice"
        result = await self.rest.call(
            "create_protection_order",
            lambda: self.exchange_private.create_order(
                symbol=spec.symbol,
                type="market",
                side=spec.side,
                amount=normalized_amount,
                price=normalized_trigger,
                params={
                    price_key: normalized_trigger,
                    "reduceOnly": True,
                    "clientOrderId": spec.cloid,
                },
            ),
            policy=WRITE_POLICY,
        )
        return dict(result)

    async def cancel_protection_orders(self, symbol: str, order_ids: list[str]) -> None:
        await self.rest.call(
            "cancel_protection_orders",
            lambda: self.cancel_orders_async(order_ids=order_ids, symbol=symbol),
            policy=IDEMPOTENT_WRITE_POLICY,
        )

    async def fetch_ohlcv_async(
        self, symbol: str, timeframe: str, fromDate: datetime, toDate: datetime
    ) -> dict[Any, Any]:
        logger.debug(
            f"Fetching OHLCV data for {symbol} asynchronously from {fromDate} to {toDate} with timeframe {timeframe}"
        )
        ohlcv: dict[Any, Any] = await self.rest.call(
            "fetch_ohlcv",
            lambda: self.exchange_public.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=int(fromDate.timestamp() * 1000),
                limit=None,
            ),
        )
        if ohlcv:
            logger.debug(
                f"OHLCV data fetched for {symbol}: {len(ohlcv)} records (async)"
            )
            return ohlcv
        else:
            logger.error(f"OHLCV data not found for symbol {symbol}")
            raise Exception(f"OHLCV data not found for symbol {symbol}")

    async def fetch_currency_async(self) -> dict[Any, Any]:
        logger.debug("Fetching currency data asynchronously")
        currency: dict[Any, Any] = await self.exchange_public.fetch_currencies()
        if currency:
            logger.debug(f"Currency data fetched: {len(currency)} currencies (async)")
            return currency
        else:
            logger.error("Currency data not found")
            raise Exception("Currency data not found")

    async def create_order_spot_async(
        self, amountByUSDT: float, symbol: str
    ) -> tuple[Any, SpotOrderResult]:
        logger.warning("create_order_spot_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "create_order_spot_async is not yet implemented for HyperLiquid"
        )

    async def create_order_perp_long_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        raise RuntimeError(
            "unsafe legacy order API is disabled; use IdempotentOrderExecutor"
        )

    async def create_order_perp_short_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        raise RuntimeError(
            "unsafe legacy order API is disabled; use IdempotentOrderExecutor"
        )

    async def close_all_positions_perp_async(
        self,
        side: PositionSide = PositionSide.ALL,
        close_symbol: Optional[str] = None,
    ) -> list[Any]:
        raise RuntimeError(
            "unsafe legacy close API is disabled; use IdempotentOrderExecutor "
            "with a reduce-only intent"
        )

    async def fetch_average_buy_price_spot_async(self, symbol: str) -> float:
        logger.warning(
            "fetch_average_buy_price_spot_async not yet implemented for HyperLiquid"
        )
        raise NotImplementedError(
            "fetch_average_buy_price_spot_async is not yet implemented for HyperLiquid"
        )

    async def fetch_close_orders_all_async(self, symbol: str) -> list[dict[str, Any]]:
        logger.warning(
            "fetch_close_orders_all_async not yet implemented for HyperLiquid"
        )
        raise NotImplementedError(
            "fetch_close_orders_all_async is not yet implemented for HyperLiquid"
        )

    async def fetch_open_orders_all_async(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch all open orders for a symbol."""
        logger.debug(f"Fetching open orders for {symbol}")
        orders = await self.exchange_public.fetch_open_orders(symbol)
        logger.debug(f"Found {len(orders)} open orders for {symbol}")
        return orders

    async def fetch_canceled_orders_all_async(
        self, symbol: str
    ) -> list[dict[str, Any]]:
        logger.warning(
            "fetch_canceled_orders_all_async not yet implemented for HyperLiquid"
        )
        raise NotImplementedError(
            "fetch_canceled_orders_all_async is not yet implemented for HyperLiquid"
        )

    async def fetch_tp_sl_info(
        self, symbol: str
    ) -> HyperliquidTakeProfitStopLossPositionInfo | None:
        current_orders = await self.fetch_open_orders_all_async(symbol=symbol)

        stop_loss_orders = [
            order
            for order in current_orders
            if order.get("info", {}).get("orderType") == "Stop Market"
        ]
        take_profit_orders = [
            order
            for order in current_orders
            if order.get("info", {}).get("orderType") == "Take Profit Market"
        ]

        if not stop_loss_orders or not take_profit_orders:
            logger.debug(f"No TP/SL orders found for symbol {symbol}")
            return None

        stoploss_order_id = stop_loss_orders[0].get("id", "")
        stoploss_trigger_price = stop_loss_orders[0].get("triggerPrice", 0)
        takeprofit_order_id = take_profit_orders[0].get("id", "")
        takeprofit_trigger_price = take_profit_orders[0].get("triggerPrice", 0)

        return HyperliquidTakeProfitStopLossPositionInfo(
            symbol=symbol,
            take_profit_order_id=takeprofit_order_id,
            stop_loss_order_id=stoploss_order_id,
            take_profit_trigger_price=takeprofit_trigger_price,
            stop_loss_trigger_price=stoploss_trigger_price,
        )

    async def create_or_update_tp_sl_async(
        self,
        symbol: str,
        side: PositionSide,
        takeprofit_order_id: str,
        stoploss_order_id: str,
        take_profit_trigger_price: float,
        stop_loss_trigger_price: float,
    ) -> HyperliquidTakeProfitStopLossPositionInfo | None:
        raise RuntimeError(
            "unsafe cancel-then-create TP/SL update is disabled; "
            "use ProtectionReconciler with the exchange position snapshot"
        )

    async def cancel_orders_async(
        self,
        order_ids: list[str],
        symbol: str,
    ) -> Any:
        """
        Cancel an existing order.
        Args:
            order_id: The ID of the order to cancel
            symbol: Trading symbol
        Returns:
            Canceled order result
        """
        logger.info(f"Canceling order {order_ids} for {symbol}")
        try:
            result = await self.exchange_private.cancel_orders(
                ids=order_ids,
                symbol=symbol,
            )
            logger.info(f"Successfully canceled order {order_ids}")
            return result
        except Exception as e:
            logger.error(f"Failed to cancel order {order_ids}: {e}")
            raise

    async def get_current_spot_pnl_async(self, symbol: str) -> float:
        logger.warning("get_current_spot_pnl_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "get_current_spot_pnl_async is not yet implemented for HyperLiquid"
        )

    async def get_spot_portfolio_async(self) -> list[SpotAsset]:
        logger.warning("get_spot_portfolio_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "get_spot_portfolio_async is not yet implemented for HyperLiquid"
        )

    async def subscribe_ohlcv_ws(
        self, symbol: str, interval: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        Subscribe to OHLCV (candle) updates via WebSocket.

        Args:
            symbol: Trading pair symbol (e.g., "XRP/USDC:USDC")
            interval: Candle interval (e.g., "1m", "5m", "1h", "1d")
            callback: Callback function to handle incoming candle data

        Example:
            async def handle_candle(candles):
                for candle in candles:
                    print(f"New candle: {candle}")

            await exchange.subscribe_ohlcv_ws("XRP/USDC:USDC", "1m", handle_candle)
        """
        # Convert CCXT symbol format to HyperLiquid format
        # XRP/USDC:USDC -> XRP
        coin = symbol.split("/")[0]

        # Connect WebSocket if not already connected
        if self.ws_client.ws is None:
            await self.ws_client.connect()

        # Subscribe to candle data
        await self.ws_client.subscribe_candle(coin, interval, callback)
        logger.info(
            f"Subscribed to {symbol} ({coin}) OHLCV data with {interval} interval via WebSocket"
        )

    async def subscribe_trades_ws(
        self, symbol: str, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        Subscribe to trade updates via WebSocket.

        Args:
            symbol: Trading pair symbol (e.g., "XRP/USDC:USDC")
            callback: Callback function to handle incoming trade data
        """
        coin = symbol.split("/")[0]

        if self.ws_client.ws is None:
            await self.ws_client.connect()

        await self.ws_client.subscribe_trade(coin=coin, callback=callback)
        logger.info(f"Subscribed to {symbol} ({coin}) trade data via WebSocket")

    async def subscribe_userFills_ws(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        if self.ws_client.ws is None:
            await self.ws_client.connect()

        await self.ws_client.subscribe_userFills(
            walletAddress=self.exchange_public.walletAddress, callback=callback
        )
        logger.info("Subscribed to authenticated user fills data")

    async def start_ws_listener(self) -> None:
        """
        Start listening for WebSocket messages.

        This should be run as a background task.

        Example:
            # Create background task for WebSocket listener
            listener_task = asyncio.create_task(exchange.start_ws_listener())

            # Subscribe to data
            await exchange.subscribe_ohlcv_ws("XRP/USDC:USDC", "1m", callback)

            # ... do other work ...

            # Clean up
            await exchange.close()  # This will stop the listener
        """
        await self.ws_client.listen()

    async def unsubscribe_ohlcv_ws(self, symbol: str, interval: str) -> None:
        """
        Unsubscribe from OHLCV updates via WebSocket.

        Args:
            symbol: Trading pair symbol (e.g., "XRP/USDC:USDC")
            interval: Candle interval (e.g., "1m", "5m", "1h", "1d")
        """
        # Convert CCXT symbol format to HyperLiquid format
        coin = symbol.split("/")[0]

        await self.ws_client.unsubscribe_candle(coin, interval)
        logger.info(
            f"Unsubscribed from {symbol} ({coin}) OHLCV data with {interval} interval"
        )
