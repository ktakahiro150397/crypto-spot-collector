from dataclasses import dataclass
from datetime import datetime
from typing import Any

import ccxt
from loguru import logger

# bybit.enable_demo_trading(enable=True)


@dataclass
class SpotOrderResult:
    """スポット注文の結果を格納するクラス"""
    order_id: str
    symbol: str
    amount: float  # 実際に注文した数量
    price: float   # 実際に注文した価格
    order_value: float  # 注文総額 (amount * price)
    original_order: Any  # 元のorder情報


class BybitExchange():
    def __init__(self, apiKey: str, secret: str) -> None:
        logger.info("Initializing Bybit exchange client")
        self.exchange = ccxt.bybit({
            'apiKey': apiKey,
            "secret": secret,
        })
        logger.info("Bybit exchange client initialized successfully")

    def fetch_balance(self) -> Any:
        logger.debug("Fetching account balance")
        balance = self.exchange.fetch_balance()
        logger.debug("Account balance fetched successfully")
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

    def create_order_spot(self, amountByUSDT: float, symbol: str) -> tuple[Any, SpotOrderResult]:
        logger.info(
            f"Creating spot order for {symbol} with {amountByUSDT} USDT")

        # 価格の精度を調整
        if symbol in ["POL", "DOGE"]:
            digit = 1
        elif symbol in ["XRP", "WLD"]:
            digit = 2
        elif symbol in ["SOL", "AVAX", "HYPE"]:
            digit = 3
        elif symbol in ["BNB"]:
            digit = 4
        elif symbol in ["ETH", "LTC", "XAUT"]:
            digit = 5
        elif symbol in ["BTC"]:
            digit = 6
        else:
            logger.error(f"Unsupported symbol {symbol} for spot order")
            raise Exception(f"Unsupported symbol {symbol} for spot order")

        logger.debug(f"Using precision digit: {digit} for {symbol}")

        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = self.fetch_price(symbol)["last"]
        limit_price = current_price * 0.995  # 0.5%安い価格で指値買い
        limit_price = round(limit_price, digit)

        logger.debug(
            f"Current price: {current_price}, Limit price: {limit_price}")

        # 希望注文額から数量を計算
        buy_amount = amountByUSDT / limit_price
        buy_amount = round(buy_amount, digit)

        # 精度調整後に注文額が1USDT未満になる場合、1USDTを超える最小値に調整
        order_value = buy_amount * limit_price
        if order_value < 1:
            logger.debug(
                f"Order value {order_value} < 1 USDT, adjusting amount")
            # 1USDTを超える最小の数量を計算
            buy_amount = round(1 / limit_price, digit)
            # 丸めた結果がまだ1未満の場合、最小単位ずつ増やす
            min_increment = 10 ** (-digit)  # digit=3なら0.001、digit=2なら0.01
            while buy_amount * limit_price < 1:
                buy_amount = round(buy_amount + min_increment, digit)
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
