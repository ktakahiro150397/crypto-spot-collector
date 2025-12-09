from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Callable, Optional

import ccxt.async_support as ccxt_async
from loguru import logger

from crypto_spot_collector.exchange.hyperliquid_ws import HyperLiquidWebSocket
from crypto_spot_collector.exchange.interface import IExchange
from crypto_spot_collector.exchange.trailingstop.trailingstop_position import (
    TrailingStopPositionHyperLiquid,
)
from crypto_spot_collector.exchange.types import (
    PositionSide,
    SpotAsset,
    SpotOrderResult,
)


@dataclass
class HyperliquidTakeProfitStopLossPositionInfo:
    symbol: str
    take_profit_order_id: str
    stop_loss_order_id: str
    take_profit_trigger_price: float
    stop_loss_trigger_price: float


class HyperLiquidExchange(IExchange):
    def __init__(self,
                 mainWalletAddress: str,
                 apiWalletAddress: str,
                 privateKey: str,
                 take_profit_rate: float,
                 stop_loss_rate: float,
                 leverage: int,
                 testnet: bool = False,) -> None:
        logger.info("Initializing HyperLiquid exchange client")
        self.exchange_public = ccxt_async.hyperliquid({
            "walletAddress": mainWalletAddress,
        })

        self.exchange_private = ccxt_async.hyperliquid({
            "walletAddress": apiWalletAddress,
            "privateKey": privateKey,
        })

        if testnet:
            self.exchange_public.set_sandbox_mode(True)
            self.exchange_private.set_sandbox_mode(True)
            logger.info("HyperLiquid exchange set to testnet mode")

        self.take_profit_rate = take_profit_rate
        self.stop_loss_rate = stop_loss_rate
        self.leverage = leverage

        # WebSocketクライアントの初期化
        self.ws_client = HyperLiquidWebSocket(testnet=testnet)

        logger.info(
            f"HyperLiquid exchange client initialized successfully. "
            f"Take Profit Rate: {self.take_profit_rate * 100:.2f}%, "
            f"Stop Loss Rate: {self.stop_loss_rate * 100:.2f}%, "
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
        exc_tb: Optional[TracebackType]
    ) -> bool:
        """Async context manager exit - automatically closes resources"""
        logger.debug("Exiting HyperLiquidExchange async context")
        await self.close()
        return False

    async def close(self) -> None:
        """Explicitly close all exchange connections"""
        logger.info("Closing HyperLiquid exchange connections")
        if hasattr(self, 'exchange_public') and self.exchange_public:
            await self.exchange_public.close()
            logger.debug("Public exchange connection closed")
        if hasattr(self, 'exchange_private') and self.exchange_private:
            await self.exchange_private.close()
            logger.debug("Private exchange connection closed")
        if hasattr(self, 'ws_client') and self.ws_client:
            await self.ws_client.disconnect()
            logger.debug("WebSocket connection closed")
        logger.info("All HyperLiquid exchange connections closed successfully")

    async def fetch_balance_async(self) -> Any:
        logger.debug("Fetching account balance asynchronously")
        balance = await self.exchange_public.fetch_balance()
        logger.debug("Account balance fetched successfully (async)")
        return balance

    async def fetch_free_usdt_async(self) -> float:
        logger.debug("Fetching free USDT balance asynchronously")
        balance = await self.fetch_balance_async()

        logger.debug(f"Balance data: {balance}")

        free_usdt = balance["free"]["USDC"]
        return float(free_usdt)

    async def fetch_price_async(self, symbol: str) -> dict[Any, Any]:
        logger.debug(f"Fetching price for {symbol} asynchronously")
        ticker: dict[Any, Any] = await self.exchange_public.fetch_ticker(symbol)
        if 'last' in ticker:
            logger.debug(f"Price for {symbol}: {ticker['last']} (async)")
            return ticker
        else:
            logger.error(f"Price not found for symbol {symbol}")
            raise Exception(
                f"symbol = {symbol} | Price not found in ticker data")

    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str,
        fromDate: datetime,
        toDate: datetime
    ) -> dict[Any, Any]:
        logger.debug(
            f"Fetching OHLCV data for {symbol} asynchronously from {fromDate} to {toDate} with timeframe {timeframe}")
        ohlcv: dict[Any, Any] = await self.exchange_public.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            since=int(fromDate.timestamp() * 1000),
            limit=None
        )
        if ohlcv:
            logger.debug(
                f"OHLCV data fetched for {symbol}: {len(ohlcv)} records (async)")
            return ohlcv
        else:
            logger.error(f"OHLCV data not found for symbol {symbol}")
            raise Exception(f"OHLCV data not found for symbol {symbol}")

    async def fetch_currency_async(self) -> dict[Any, Any]:
        logger.debug("Fetching currency data asynchronously")
        currency: dict[Any, Any] = await self.exchange_public.fetch_currencies()
        if currency:
            logger.debug(
                f"Currency data fetched: {len(currency)} currencies (async)")
            return currency
        else:
            logger.error("Currency data not found")
            raise Exception("Currency data not found")

    async def create_order_spot_async(
        self,
        amountByUSDT: float,
        symbol: str
    ) -> tuple[Any, SpotOrderResult]:
        logger.warning(
            "create_order_spot_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "create_order_spot_async is not yet implemented for HyperLiquid")

    async def create_order_perp_long_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        """
        Create a perpetual long order with Take Profit and Stop Loss.

        ccxtが自動的にTP/SL注文をメイン注文と一緒に作成し、
        grouping='normalTpsl'でグループ化します。
        これによりWebUIと同じようにグルーピングされた注文が作成されます。
        """
        # 現在の市場価格を取得
        ticker = await self.fetch_price_async(symbol)
        market_price = float(ticker['last'])
        logger.debug(f"Market price for {symbol}: {market_price}")

        # 市場価格ベースでROEのTP/SL計算
        tp_trigger = market_price * (1 + self.take_profit_rate / self.leverage)
        sl_trigger = market_price * (1 - self.stop_loss_rate / self.leverage)

        result = await self.exchange_private.create_order(
            symbol=symbol,
            type="market",
            side="buy",
            amount=amount,
            price=market_price,
            params={
                "stopLoss": {
                    "type": "market",  # SLはmarketで即座に決済
                    "triggerPrice": sl_trigger,
                },
                "takeProfit": {
                    "type": "market",  # TPもmarketで即座に決済
                    "triggerPrice": tp_trigger,
                }
            }
        )

        logger.info(
            f"Perpetual long order created for {symbol} at market price {market_price} with amount {amount}. "
            f"TP trigger: {tp_trigger:.4f}, SL trigger: {sl_trigger:.4f}"
        )

        return result

    async def create_order_perp_short_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        """
        Create a perpetual short order with Take Profit and Stop Loss.
        """
        # 現在の市場価格を取得
        ticker = await self.fetch_price_async(symbol)
        market_price = float(ticker['last'])
        logger.debug(f"Market price for {symbol}: {market_price}")

        # 市場価格ベースでROEのTP/SL計算
        tp_trigger = market_price * (1 - self.take_profit_rate / self.leverage)
        sl_trigger = market_price * (1 + self.stop_loss_rate / self.leverage)

        result = await self.exchange_private.create_order(
            symbol=symbol,
            type="market",
            side="sell",
            amount=amount,
            price=market_price,
            params={
                "stopLoss": {
                    "type": "market",  # SLはmarketで即座に決済
                    "triggerPrice": sl_trigger,
                },
                "takeProfit": {
                    "type": "market",  # TPもmarketで即座に決済
                    "triggerPrice": tp_trigger,
                }
            }
        )

        logger.info(
            f"Perpetual short order created for {symbol} at market price {market_price} with amount {amount}. "
            f"TP trigger: {tp_trigger:.4f}, SL trigger: {sl_trigger:.4f}"
        )

        return result

    async def close_all_positions_perp_async(
        self,
        side: PositionSide = PositionSide.ALL,
        close_symbol: Optional[str] = None,
    ) -> list[Any]:
        logger.info(f"Closing all perpetual positions (side: {side.value})")

        # Fetch all positions
        positions = await self.exchange_public.fetch_positions()
        logger.debug(f"Fetched {len(positions)} positions")

        results: list[Any] = []

        for position in positions:
            # Skip positions with zero or missing contracts
            contracts_raw = position.get('contracts')
            if contracts_raw is None:
                logger.debug(
                    f"Skipping position with missing contracts: {position}")
                continue
            contracts = float(contracts_raw)
            if contracts == 0:
                continue

            position_side = position.get('side')
            symbol = position.get('symbol')

            if close_symbol is not None and symbol != close_symbol:
                logger.debug(
                    f"Skipping {symbol} (filter symbol: {close_symbol})")
                continue

            # Filter by side if specified
            if side == PositionSide.LONG and position_side != 'long':
                logger.debug(
                    f"Skipping {symbol} (side: {position_side}, filter: long)")
                continue
            if side == PositionSide.SHORT and position_side != 'short':
                logger.debug(
                    f"Skipping {symbol} (side: {position_side}, filter: short)")
                continue

            # Determine the side for closing order (opposite of position side)
            if position_side == 'long':
                close_side = 'sell'
            elif position_side == 'short':
                close_side = 'buy'
            else:
                logger.warning(
                    f"Unexpected position side '{position_side}' for {symbol}, skipping"
                )
                continue

            logger.info(
                f"Closing position: {symbol}, side: {position_side}, "
                f"contracts: {contracts}, close_side: {close_side}"
            )

            try:
                # Get current price for calculate slippage in Hyperliquid
                price = await self.fetch_price_async(symbol)
                current_price = price['last']

                # Create a market order to close the position
                result = await self.exchange_private.create_order(
                    symbol=symbol,
                    type='market',
                    side=close_side,
                    amount=contracts,
                    price=current_price,
                    params={
                        'reduceOnly': True,
                    }
                )
                results.append(result)
                logger.info(
                    f"Successfully closed position for {symbol}: {result.get('id', 'N/A')}"
                )
            except Exception as e:
                logger.error(f"Failed to close position for {symbol}: {e}")
                raise

        logger.info(f"Closed {len(results)} positions")
        return results

    async def fetch_average_buy_price_spot_async(self, symbol: str) -> float:
        logger.warning(
            "fetch_average_buy_price_spot_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_average_buy_price_spot_async is not yet implemented for HyperLiquid")

    async def fetch_close_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        logger.warning(
            "fetch_close_orders_all_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_close_orders_all_async is not yet implemented for HyperLiquid")

    async def fetch_open_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        """Fetch all open orders for a symbol."""
        logger.debug(f"Fetching open orders for {symbol}")
        orders = await self.exchange_public.fetch_open_orders(symbol)
        logger.debug(f"Found {len(orders)} open orders for {symbol}")
        return orders

    async def fetch_canceled_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        logger.warning(
            "fetch_canceled_orders_all_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_canceled_orders_all_async is not yet implemented for HyperLiquid")

    async def fetch_tp_sl_info(
        self,
        symbol: str
    ) -> HyperliquidTakeProfitStopLossPositionInfo | None:
        current_orders = await self.fetch_open_orders_all_async(symbol=symbol)

        stop_loss_orders = [
            order for order in current_orders if order.get("info", {}).get("orderType") == "Stop Market"
        ]
        print("Current Stop Loss Orders:", stop_loss_orders)
        take_profit_orders = [
            order for order in current_orders if order.get("info", {}).get("orderType") == "Take Profit Market"
        ]
        print("Current Take Profit Orders:", take_profit_orders)

        if not stop_loss_orders or not take_profit_orders:
            logger.info(f"No TP/SL orders found for symbol {symbol}")
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
        # 現在のTP/SL注文をキャンセル
        await self.cancel_orders_async(
            order_ids=[takeprofit_order_id, stoploss_order_id],
            symbol=symbol,
        )

        side = "sell" if side == PositionSide.LONG else "buy"

        # 新しいTP/SL注文を作成
        await self.exchange_private.create_orders(
            [
                {
                    "symbol": symbol,
                    "type": "market",
                    "side": side,
                    "amount": 0,
                    "price": stop_loss_trigger_price,
                    "params": {
                        "stopLossPrice": stop_loss_trigger_price,
                        "reduceOnly": True,
                    }
                },
                {
                    "symbol": symbol,
                    "type": "market",
                    "side": side,
                    "amount": 0,
                    "price": take_profit_trigger_price,
                    "params": {
                        "takeProfitPrice": take_profit_trigger_price,
                        "reduceOnly": True,
                    }
                },
            ]
        )

        logger.info(
            "Successfully created stop loss order")

        # 更新後のTP/SL注文情報を返す
        tp_sl_info = await self.fetch_tp_sl_info(
            symbol=symbol,
        )
        return tp_sl_info

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
        logger.warning(
            "get_current_spot_pnl_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "get_current_spot_pnl_async is not yet implemented for HyperLiquid")

    async def get_spot_portfolio_async(self) -> list[SpotAsset]:
        logger.warning(
            "get_spot_portfolio_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "get_spot_portfolio_async is not yet implemented for HyperLiquid")

    async def subscribe_ohlcv_ws(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None]
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
        coin = symbol.split('/')[0]

        # Connect WebSocket if not already connected
        if self.ws_client.ws is None:
            await self.ws_client.connect()

        # Subscribe to candle data
        await self.ws_client.subscribe_candle(coin, interval, callback)
        logger.info(
            f"Subscribed to {symbol} ({coin}) OHLCV data with {interval} interval via WebSocket"
        )

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
        coin = symbol.split('/')[0]

        await self.ws_client.unsubscribe_candle(coin, interval)
        logger.info(
            f"Unsubscribed from {symbol} ({coin}) OHLCV data with {interval} interval"
        )
