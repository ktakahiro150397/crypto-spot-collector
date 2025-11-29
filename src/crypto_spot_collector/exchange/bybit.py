from datetime import datetime
from types import TracebackType
from typing import Any, Optional

import ccxt
import ccxt.async_support as ccxt_async
from loguru import logger

from crypto_spot_collector.exchange.interface import IExchange
from crypto_spot_collector.exchange.types import SpotAsset, SpotOrderResult
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository

# bybit.enable_demo_trading(enable=True)


class BybitExchange(IExchange):
    def __init__(self, apiKey: str, secret: str) -> None:
        logger.info("Initializing Bybit exchange client")
        self.exchange = ccxt.bybit({
            'apiKey': apiKey,
            "secret": secret
        })

        self.exchange_async = ccxt_async.bybit({
            'apiKey': apiKey,
            "secret": secret
        })

        self.repo_trade_data = TradeDataRepository()
        logger.info("Bybit exchange client initialized successfully")

    async def __aenter__(self) -> "IExchange":
        """Async context manager entry"""
        logger.debug("Entering BybitExchange async context")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> bool:
        """Async context manager exit - automatically closes resources"""
        logger.debug("Exiting BybitExchange async context")
        await self.close()
        return False

    async def close(self) -> None:
        """Explicitly close all exchange connections"""
        logger.info("Closing Bybit exchange connections")
        if hasattr(self, 'exchange_async') and self.exchange_async:
            await self.exchange_async.close()
            logger.debug("Async exchange connection closed")
        if hasattr(self, 'exchange') and self.exchange:
            # 同期版のexchangeもcloseメソッドがある場合はクローズ
            if hasattr(self.exchange, 'close'):
                self.exchange.close()
                logger.debug("Sync exchange connection closed")
        logger.info("All Bybit exchange connections closed successfully")

    def fetch_balance(self) -> Any:
        logger.debug("Fetching account balance")
        balance = self.exchange.fetch_balance()
        logger.debug("Account balance fetched successfully")
        return balance

    async def fetch_balance_async(self) -> Any:
        logger.debug("Fetching account balance asynchronously")
        balance = await self.exchange_async.fetch_balance()
        logger.debug("Account balance fetched successfully (async)")
        return balance

    def fetch_free_usdt(self) -> float:
        logger.debug("Fetching free USDT balance")
        balance = self.fetch_balance()

        # USDTのfree残高を取得
        for value in balance["info"]["result"]["list"]:
            for coin in value["coin"]:
                if coin["coin"] == "USDT":
                    free_usdt = float(coin["equity"]) - float(coin["locked"])
                    logger.info(f"Free USDT balance: {free_usdt}")
                    return free_usdt
                # equity = float(coin["equity"])
                # locked = float(coin["locked"])

                # logger.debug(
                #     f"{coin['coin']}: equity : {equity} | locked: {locked} | free: {equity - locked}")

        logger.warning("USDT balance not found, returning 0")
        return 0

    async def fetch_free_usdt_async(self) -> float:
        logger.debug("Fetching free USDT balance asynchronously")
        balance = await self.fetch_balance_async()

        # USDTのfree残高を取得
        for value in balance["info"]["result"]["list"]:
            for coin in value["coin"]:
                if coin["coin"] == "USDT":
                    free_usdt = float(coin["equity"]) - float(coin["locked"])
                    logger.info(f"Free USDT balance: {free_usdt} (async)")
                    return free_usdt

        logger.warning("USDT balance not found, returning 0 (async)")
        return 0

    def fetch_price(self, symbol: str) -> dict[Any, Any]:
        """

        """
        logger.debug(f"Fetching price for {symbol}")
        ticker: dict[Any, Any] = self.exchange.fetch_ticker(symbol)
        if 'last' in ticker:
            logger.debug(f"Price for {symbol}: {ticker['last']}")
            return ticker
        else:
            logger.error(f"Price not found for symbol {symbol}")
            raise Exception(
                f"symbol = {symbol} | Price not found in ticker data")

    async def fetch_price_async(self, symbol: str) -> dict[Any, Any]:
        """

        """
        logger.debug(f"Fetching price for {symbol} asynchronously")
        ticker: dict[Any, Any] = await self.exchange_async.fetch_ticker(symbol)
        if 'last' in ticker:
            logger.debug(f"Price for {symbol}: {ticker['last']} (async)")
            return ticker
        else:
            logger.error(f"Price not found for symbol {symbol}")
            raise Exception(
                f"symbol = {symbol} | Price not found in ticker data")

    def fetch_ohlcv(self, symbol: str, timeframe: str, fromDate: datetime, toDate: datetime) -> dict[Any, Any]:
        logger.debug(
            f"Fetching OHLCV data for {symbol} ({timeframe}) from {fromDate} to {toDate}")
        ohlcv: dict[Any, Any] = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=int(fromDate.timestamp() * 1000),
            params={
                "until": int(toDate.timestamp() * 1000)
            },
            limit=1000)
        if ohlcv:
            logger.debug(
                f"OHLCV data fetched for {symbol}: {len(ohlcv)} records")
            return ohlcv
        else:
            logger.error(f"OHLCV data not found for symbol {symbol}")
            raise Exception(
                f"symbol = {symbol} | OHLCV data not found")

    async def fetch_ohlcv_async(self, symbol: str, timeframe: str, fromDate: datetime, toDate: datetime) -> dict[Any, Any]:
        logger.debug(
            f"Fetching OHLCV data for {symbol} ({timeframe}) from {fromDate} to {toDate} asynchronously")
        ohlcv: dict[Any, Any] = await self.exchange_async.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=int(fromDate.timestamp() * 1000),
            params={
                "until": int(toDate.timestamp() * 1000)
            },
            limit=1000)
        if ohlcv:
            logger.debug(
                f"OHLCV data fetched for {symbol}: {len(ohlcv)} records (async)")
            return ohlcv
        else:
            logger.error(f"OHLCV data not found for symbol {symbol}")
            raise Exception(
                f"symbol = {symbol} | OHLCV data not found")

    def fetch_currency(self) -> dict[Any, Any]:
        logger.debug("Fetching currency data")
        currency: dict[Any, Any] = self.exchange.fetch_currencies()
        if currency:
            logger.debug(f"Currency data fetched: {len(currency)} currencies")
            return currency
        else:
            logger.error("Currency data not found")
            raise Exception(
                "Currency data not found")

    async def fetch_currency_async(self) -> dict[Any, Any]:
        logger.debug("Fetching currency data asynchronously")
        currency: dict[Any, Any] = await self.exchange_async.fetch_currencies()
        if currency:
            logger.debug(
                f"Currency data fetched: {len(currency)} currencies (async)")
            return currency
        else:
            logger.error("Currency data not found")
            raise Exception(
                "Currency data not found")

    def create_order_spot(self, amountByUSDT: float, symbol: str) -> tuple[Any, SpotOrderResult]:
        logger.info(
            f"Creating spot order for {symbol} with {amountByUSDT} USDT")

        # 数量（個数）の精度を設定
        if symbol in ["POL", "DOGE"]:
            amount_digit = 1  # 0.1単位
        elif symbol in ["XRP", "WLD"]:
            amount_digit = 2  # 0.01単位
        elif symbol in ["SOL", "AVAX", "HYPE", "LINK"]:
            amount_digit = 3  # 0.001単位
        elif symbol in ["BNB"]:
            amount_digit = 4  # 0.0001単位
        elif symbol in ["ETH", "LTC", "XAUT"]:
            amount_digit = 5  # 0.00001単位
        elif symbol in ["BTC"]:
            amount_digit = 6  # 0.000001単位
        else:
            logger.error(f"Unsupported symbol {symbol} for spot order")
            raise Exception(f"Unsupported symbol {symbol} for spot order")

        # 価格は常に5桁の精度
        price_digit = 5

        logger.debug(
            f"Using amount precision: {amount_digit}, price precision: {price_digit} for {symbol}")

        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = self.fetch_price(symbol)["last"]
        limit_price = current_price * 0.995  # 0.5%安い価格で指値買い
        limit_price = round(limit_price, price_digit)

        logger.debug(
            f"Current price: {current_price}, Limit price: {limit_price}")

        # 希望注文額から数量を計算
        buy_amount = amountByUSDT / limit_price
        buy_amount = round(buy_amount, amount_digit)

        # 精度調整後に注文額が1USDT未満になる場合、1USDTを超える最小値に調整
        order_value = buy_amount * limit_price
        if order_value < 1:
            logger.debug(
                f"Order value {order_value} < 1 USDT, adjusting amount")
            # 1USDTを超える最小の数量を計算
            buy_amount = round(1 / limit_price, amount_digit)
            # 丸めた結果がまだ1未満の場合、最小単位ずつ増やす
            # amount_digit=3なら0.001、amount_digit=2なら0.01
            min_increment = 10 ** (-amount_digit)
            while buy_amount * limit_price < 1:
                buy_amount = round(buy_amount + min_increment, amount_digit)
            logger.debug(f"Adjusted buy amount: {buy_amount}")

        final_order_value = buy_amount * limit_price
        logger.info(
            f"Placing spot buy order: symbol={symbol}, amount={buy_amount}, price={limit_price}, order_value={final_order_value:.2f} USDT")

        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=buy_amount,
                price=limit_price,
                params={}
            )
            logger.success(
                f"Spot order created successfully for {symbol}: Order ID {order.get('id', 'N/A')}")

            # DBへ登録
            self.repo_trade_data.create_or_update_trade_data(
                cryptocurrency_name=symbol.replace("/USDT", ""),
                exchange_name="bybit",
                trade_id=order['id'],
                status='OPEN',
                position_type='LONG',
                is_spot=True,
                leverage_ratio=1.00,
                price=limit_price,
                quantity=buy_amount,
                fee=order['fee']['cost'] *
                order['price'] if order['fee'] else 0,  # feeをUSDT換算
                timestamp_utc=datetime.fromtimestamp(
                    order['timestamp'] / 1000) if order['timestamp'] in order else None,
            )

            # 結果をSpotOrderResultクラスにまとめる
            result = SpotOrderResult(
                order_id=order.get('id', 'N/A'),
                symbol=symbol,
                amount=buy_amount,
                price=limit_price,
                order_value=final_order_value,
                original_order=order
            )

            return order, result

        except Exception as e:
            logger.error(f"Failed to create spot order for {symbol}: {e}")
            raise

    async def create_order_spot_async(self, amountByUSDT: float, symbol: str) -> tuple[Any, SpotOrderResult]:
        logger.info(
            f"Creating spot order for {symbol} with {amountByUSDT} USDT asynchronously")

        # 数量（個数）の精度を設定
        if symbol in ["POL", "DOGE"]:
            amount_digit = 1  # 0.1単位
        elif symbol in ["XRP", "WLD"]:
            amount_digit = 2  # 0.01単位
        elif symbol in ["SOL", "AVAX", "HYPE", "LINK"]:
            amount_digit = 3  # 0.001単位
        elif symbol in ["BNB"]:
            amount_digit = 4  # 0.0001単位
        elif symbol in ["ETH", "LTC", "XAUT"]:
            amount_digit = 5  # 0.00001単位
        elif symbol in ["BTC"]:
            amount_digit = 6  # 0.000001単位
        else:
            logger.error(f"Unsupported symbol {symbol} for spot order")
            raise Exception(f"Unsupported symbol {symbol} for spot order")

        # 価格は常に5桁の精度
        price_digit = 5

        logger.debug(
            f"Using amount precision: {amount_digit}, price precision: {price_digit} for {symbol}")

        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = (await self.fetch_price_async(symbol))["last"]
        limit_price = current_price * 0.995  # 0.5%安い価格で指値買い
        limit_price = round(limit_price, price_digit)

        logger.debug(
            f"Current price: {current_price}, Limit price: {limit_price}")

        # 希望注文額から数量を計算
        buy_amount = amountByUSDT / limit_price
        buy_amount = round(buy_amount, amount_digit)

        # 精度調整後に注文額が1USDT未満になる場合、1USDTを超える最小値に調整
        order_value = buy_amount * limit_price
        if order_value < 1:
            logger.debug(
                f"Order value {order_value} < 1 USDT, adjusting amount")
            # 1USDTを超える最小の数量を計算
            buy_amount = round(1 / limit_price, amount_digit)
            # 丸めた結果がまだ1未満の場合、最小単位ずつ増やす
            # amount_digit=3なら0.001、amount_digit=2なら0.01
            min_increment = 10 ** (-amount_digit)
            while buy_amount * limit_price < 1:
                buy_amount = round(buy_amount + min_increment, amount_digit)
            logger.debug(f"Adjusted buy amount: {buy_amount}")

        final_order_value = buy_amount * limit_price
        logger.info(
            f"Placing spot buy order: symbol={symbol}, amount={buy_amount}, price={limit_price}, order_value={final_order_value:.2f} USDT (async)")

        try:
            order = await self.exchange_async.create_order(
                symbol=symbol,
                type='limit',
                side='buy',
                amount=buy_amount,
                price=limit_price,
                params={}
            )
            logger.success(
                f"Spot order created successfully for {symbol}: Order ID {order.get('id', 'N/A')} (async)")

            # DBへ登録
            self.repo_trade_data.create_or_update_trade_data(
                cryptocurrency_name=symbol.replace("/USDT", ""),
                exchange_name="bybit",
                trade_id=order['id'],
                status='OPEN',
                position_type='LONG',
                is_spot=True,
                leverage_ratio=1.00,
                price=limit_price,
                quantity=buy_amount,
                fee=order['fee']['cost'] *
                order['price'] if order['fee'] else 0,  # feeをUSDT換算
                timestamp_utc=datetime.fromtimestamp(
                    order['timestamp'] / 1000) if order['timestamp'] in order else None,
            )

            # 結果をSpotOrderResultクラスにまとめる
            result = SpotOrderResult(
                order_id=order.get('id', 'N/A'),
                symbol=symbol,
                amount=buy_amount,
                price=limit_price,
                order_value=final_order_value,
                original_order=order
            )

            return order, result

        except Exception as e:
            logger.error(f"Failed to create spot order for {symbol}: {e}")
            raise

    async def create_order_perp_long_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        raise NotImplementedError(
            "create_order_perp_long_async is not yet implemented for Bybit")

    async def create_order_perp_short_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        raise NotImplementedError(
            "create_order_perp_short_async is not yet implemented for Bybit")

    def fetch_average_buy_price_spot(self, symbol: str) -> float:
        logger.debug(f"Fetching average buy price for {symbol} spot")
        try:
            # 2025/01/01 以降の注文を取得(msで指定)
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            orders = self.exchange.fetch_closed_orders(
                symbol=f"{symbol}/USDT",
                since=since_ms,
                limit=100,
                params={}
            )
            buy_orders = [
                order for order in orders if order['side'] == 'buy' and order['status'] == 'closed']
            total_cost = sum(
                float(order['cost']) for order in buy_orders)
            total_amount = sum(
                float(order['amount']) for order in buy_orders)

            if total_amount == 0:
                logger.warning(
                    f"No completed buy orders found for {symbol} spot")
                return 0.0

            logger.debug(
                f"Total cost: {total_cost}, Total amount: {total_amount}")

            average_price = total_cost / total_amount
            logger.info(
                f"Average buy price for {symbol} spot: {average_price}")
            return average_price

        except Exception as e:
            logger.error(
                f"Failed to fetch average buy price for {symbol} spot: {e}")
            raise

    async def fetch_average_buy_price_spot_async(self, symbol: str) -> float:
        logger.debug(
            f"Fetching average buy price for {symbol} spot asynchronously")
        try:
            # 2025/01/01 以降の注文を取得(msで指定)
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            orders = await self.exchange_async.fetch_closed_orders(
                symbol=f"{symbol}/USDT",
                since=since_ms,
                limit=100,
                params={}
            )
            buy_orders = [
                order for order in orders if order['side'] == 'buy' and order['status'] == 'closed']
            total_cost = sum(
                float(order['cost']) for order in buy_orders)
            total_amount = sum(
                float(order['amount']) for order in buy_orders)

            if total_amount == 0:
                logger.warning(
                    f"No completed buy orders found for {symbol} spot (async)")
                return 0.0

            logger.debug(
                f"Total cost: {total_cost}, Total amount: {total_amount}")

            average_price = total_cost / total_amount
            logger.info(
                f"Average buy price for {symbol} spot: {average_price} (async)")
            return average_price

        except Exception as e:
            logger.error(
                f"Failed to fetch average buy price for {symbol} spot: {e}")
            raise

    def fetch_close_orders_all(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(f"Fetching all closed orders for {symbol} spot")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = self.exchange.fetch_closed_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total closed orders fetched for {symbol} spot: {len(all_orders)}")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch closed orders for {symbol} spot: {e}")
            raise

    async def fetch_close_orders_all_async(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(
            f"Fetching all closed orders for {symbol} spot asynchronously")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = await self.exchange_async.fetch_closed_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total closed orders fetched for {symbol} spot: {len(all_orders)} (async)")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch closed orders for {symbol} spot: {e}")
            raise

    def fetch_open_orders_all(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(f"Fetching all open orders for {symbol} spot")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching open orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = self.exchange.fetch_open_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} open orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total open orders fetched for {symbol} spot: {len(all_orders)}")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch open orders for {symbol} spot: {e}")
            raise

    async def fetch_open_orders_all_async(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(
            f"Fetching all open orders for {symbol} spot asynchronously")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching open orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = await self.exchange_async.fetch_open_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} open orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total open orders fetched for {symbol} spot: {len(all_orders)} (async)")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch open orders for {symbol} spot: {e}")
            raise

    def fetch_canceled_orders_all(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(f"Fetching all canceled orders for {symbol} spot")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching canceled orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = self.exchange.fetch_canceled_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} canceled orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total canceled orders fetched for {symbol} spot: {len(all_orders)}")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch canceled orders for {symbol} spot: {e}")
            raise

    async def fetch_canceled_orders_all_async(self, symbol: str) -> list[dict[str, Any]]:
        logger.debug(
            f"Fetching all canceled orders for {symbol} spot asynchronously")
        all_orders: list[dict[str, Any]] = []
        try:
            since_ms = int(datetime(2025, 11, 1).timestamp() * 1000)
            now_ms = int(datetime.now().timestamp() * 1000)
            seven_days_ms = 7 * 24 * 60 * 60 * 1000  # 7日間をミリ秒に変換

            while since_ms < now_ms:
                # 7日間の終了時刻を計算（今日の日付を超えないように）
                until_ms = min(since_ms + seven_days_ms, now_ms)

                logger.debug(
                    f"Fetching canceled orders from {datetime.fromtimestamp(since_ms/1000)} to {datetime.fromtimestamp(until_ms/1000)}")

                orders = await self.exchange_async.fetch_canceled_orders(
                    symbol=f"{symbol}/USDT",
                    since=since_ms,
                    limit=100,
                    params={
                        "until": until_ms,
                        "paginate": True
                    }
                )

                if orders:
                    logger.debug(
                        f"Fetched {len(orders)} canceled orders, total so far: {len(all_orders)}")
                    all_orders.extend(orders)

                # 次の7日間の開始点を設定
                since_ms = until_ms + 1

            logger.info(
                f"Total canceled orders fetched for {symbol} spot: {len(all_orders)} (async)")
            return all_orders

        except Exception as e:
            logger.error(
                f"Failed to fetch canceled orders for {symbol} spot: {e}")
            raise

    def get_current_spot_pnl(self, symbol: str) -> float:
        try:
            orders = self.fetch_close_orders_all(symbol=symbol)

            buy_orders = [
                order for order in orders if order['side'] == 'buy' and order['status'] == 'closed']
            total_cost = sum(
                float(order['cost']) for order in buy_orders)
            total_amount = sum(
                float(order['amount']) for order in buy_orders)
            total_fee_amount = sum(
                float(order['fee']['cost']) for order in buy_orders
            )

            for buy_order in buy_orders:
                logger.debug(
                    f"Buy Order - ID: {buy_order['id']}, Amount: {buy_order['amount']}, Cost: {buy_order['cost']}, Fee: {buy_order['fee']['cost']}")

            sell_orders = [
                order for order in orders if order['side'] == 'sell' and order['status'] == 'closed']
            total_sell_value = sum(
                float(order['cost']) for order in sell_orders)
            total_amount_sold = sum(
                float(order['filled']) for order in sell_orders)

            if total_amount == 0:
                logger.warning(
                    f"No completed buy orders found for {symbol} spot")
                return 0.0

            current_spot_amount = total_amount - total_fee_amount - total_amount_sold

            logger.debug(
                f"Total buy cost: {total_cost}, Total buy amount: {total_amount}, Total buy fee amount: {total_fee_amount}")
            logger.debug(
                f"Total sell value: {total_sell_value}, Total amount sold: {total_amount_sold}"
            )
            logger.debug(
                f"Current spot amount for {symbol}: {current_spot_amount}")

            average_price = total_cost / total_amount

            logger.info(
                f"Average buy price for {symbol} spot: {average_price}")

            current_price = self.fetch_price(f"{symbol}/USDT")["last"]

            pnl = round((current_price - average_price)
                        * current_spot_amount, 5)
            logger.info(
                f"Current PnL for {symbol} spot: {pnl} (Current Price: {current_price})")

            return float(pnl)
        except Exception as e:
            logger.error(
                f"Failed to fetch average buy price for {symbol} spot: {e}")
            raise

    async def get_current_spot_pnl_async(self, symbol: str) -> float:
        try:
            orders = await self.fetch_close_orders_all_async(symbol=symbol)

            buy_orders = [
                order for order in orders if order['side'] == 'buy' and order['status'] == 'closed']
            total_cost = sum(
                float(order['cost']) for order in buy_orders)
            total_amount = sum(
                float(order['amount']) for order in buy_orders)
            total_fee_amount = sum(
                float(order['fee']['cost']) for order in buy_orders
            )

            for buy_order in buy_orders:
                logger.debug(
                    f"Buy Order - ID: {buy_order['id']}, Amount: {buy_order['amount']}, Cost: {buy_order['cost']}, Fee: {buy_order['fee']['cost']}")

            sell_orders = [
                order for order in orders if order['side'] == 'sell' and order['status'] == 'closed']
            total_sell_value = sum(
                float(order['cost']) for order in sell_orders)
            total_amount_sold = sum(
                float(order['filled']) for order in sell_orders)

            if total_amount == 0:
                logger.warning(
                    f"No completed buy orders found for {symbol} spot (async)")
                return 0.0

            current_spot_amount = total_amount - total_fee_amount - total_amount_sold

            logger.debug(
                f"Total buy cost: {total_cost}, Total buy amount: {total_amount}, Total buy fee amount: {total_fee_amount}")
            logger.debug(
                f"Total sell value: {total_sell_value}, Total amount sold: {total_amount_sold}"
            )
            logger.debug(
                f"Current spot amount for {symbol}: {current_spot_amount}")

            average_price = total_cost / total_amount

            logger.info(
                f"Average buy price for {symbol} spot: {average_price} (async)")

            current_price = (await self.fetch_price_async(f"{symbol}/USDT"))["last"]

            pnl = round((current_price - average_price)
                        * current_spot_amount, 5)
            logger.info(
                f"Current PnL for {symbol} spot: {pnl} (Current Price: {current_price}) (async)")

            return float(pnl)
        except Exception as e:
            logger.error(
                f"Failed to fetch average buy price for {symbol} spot: {e}")
            raise

    def get_spot_portfolio(self) -> list[SpotAsset]:
        portfolio: list[SpotAsset] = []
        balance = self.fetch_balance()

        for value in balance["info"]["result"]["list"]:
            for coin in value["coin"]:
                logger.debug(f"Processing coin: {coin['coin']}")
                equity = float(coin["equity"])

                pnl = 0.0
                current_value = equity
                if not coin["coin"] == "USDT":
                    pnl = self.get_current_spot_pnl(coin["coin"])
                    current_value = self.fetch_price(
                        f"{coin['coin']}/USDT")["last"] * equity

                spot_asset = SpotAsset(
                    symbol=coin["coin"],
                    total_amount=equity,
                    current_value=current_value,
                    profit_loss=pnl
                )
                portfolio.append(spot_asset)

        # USDTを先頭に移動
        portfolio.sort(key=lambda x: (x.symbol != "USDT", x.symbol))

        logger.info("Spot portfolio fetched.")
        return portfolio

    async def get_spot_portfolio_async(self) -> list[SpotAsset]:
        portfolio: list[SpotAsset] = []
        balance = await self.fetch_balance_async()

        for value in balance["info"]["result"]["list"]:
            for coin in value["coin"]:
                logger.debug(f"Processing coin: {coin['coin']}")
                equity = float(coin["equity"])

                pnl = 0.0
                current_value = equity
                if not coin["coin"] == "USDT":
                    pnl = await self.get_current_spot_pnl_async(coin["coin"])
                    current_value = (await self.fetch_price_async(
                        f"{coin['coin']}/USDT"))["last"] * equity

                spot_asset = SpotAsset(
                    symbol=coin["coin"],
                    total_amount=equity,
                    current_value=current_value,
                    profit_loss=pnl
                )
                portfolio.append(spot_asset)

        # USDTを先頭に移動
        portfolio.sort(key=lambda x: (x.symbol != "USDT", x.symbol))

        logger.info("Spot portfolio fetched (async).")
        return portfolio
