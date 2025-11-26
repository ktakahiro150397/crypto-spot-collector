from datetime import datetime
from types import TracebackType
from typing import Any, Optional

import ccxt.async_support as ccxt_async
from ccxt.async_support.hyperliquid import hyperliquid
from loguru import logger

from crypto_spot_collector.exchange.interface import IExchange
from crypto_spot_collector.exchange.types import SpotAsset, SpotOrderResult


class HyperLiquidExchange(IExchange):
    def __init__(self, mainWalletAddress: str, apiWalletAddress: str, privateKey: str) -> None:
        logger.info("Initializing HyperLiquid exchange client")
        self.exchange_public = ccxt_async.hyperliquid({
            "walletAddress": mainWalletAddress,
        })

        self.exchange_private = ccxt_async.hyperliquid({
            "walletAddress": apiWalletAddress,
            "privateKey": privateKey,
        })

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
        if hasattr(self, 'exchange') and self.exchange_public:
            await self.exchange_public.close()
            logger.debug("Exchange connection closed")
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

        # USDTのfree残高を取得
        # for value in balance["info"]["result"]["list"]:
        #     for coin in value["coin"]:
        #         if coin["coin"] == "USDT":
        #             free_usdt = float(coin["equity"]) - float(coin["locked"])
        #             logger.info(f"Free USDT balance: {free_usdt} (async)")
        #             return free_usdt

        # logger.warning("USDT balance not found")
        # return 0

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
        logger.warning("fetch_ohlcv_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_ohlcv_async is not yet implemented for HyperLiquid")

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
        logger.warning(
            "fetch_open_orders_all_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_open_orders_all_async is not yet implemented for HyperLiquid")

    async def fetch_canceled_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        logger.warning(
            "fetch_canceled_orders_all_async not yet implemented for HyperLiquid")
        raise NotImplementedError(
            "fetch_canceled_orders_all_async is not yet implemented for HyperLiquid")

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
