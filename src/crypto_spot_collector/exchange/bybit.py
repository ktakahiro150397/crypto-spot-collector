from datetime import datetime
from typing import Any

import ccxt

# bybit.enable_demo_trading(enable=True)


class BybitExchange():
    def __init__(self, apiKey: str, secret: str) -> None:
        self.exchange = ccxt.bybit({
            'apiKey': apiKey,
            "secret": secret,
        })

    def fetch_balance(self) -> Any:
        return self.exchange.fetch_balance()

    def fetch_price(self, symbol: str) -> dict[Any, Any]:
        """

        """
        ticker: dict[Any, Any] = self.exchange.fetch_ticker(symbol)
        if 'last' in ticker:
            return ticker
        else:
            raise Exception(
                f"symbol = {symbol} | Price not found in ticker data")

    def fetch_ohlcv(self, symbol: str, timeframe: str, fromDate: datetime, toDate: datetime) -> dict[Any, Any]:
        ohlcv: dict[Any, Any] = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=int(fromDate.timestamp() * 1000),
            params={
                "until": int(toDate.timestamp() * 1000)
            },
            limit=1000)
        if ohlcv:
            return ohlcv
        else:
            raise Exception(
                f"symbol = {symbol} | OHLCV data not found")

    def fetch_currency(self) -> dict[Any, Any]:
        currency: dict[Any, Any] = self.exchange.fetch_currencies()
        if currency:
            return currency
        else:
            raise Exception(
                "Currency data not found")

    def create_order_spot(self, amountByUSDT: float, symbol: str) -> dict[Any, Any]:
        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = self.fetch_price(symbol)["last"]
        limit_price = current_price * 0.97  # 3%安い価格で指値買い

        # 価格の精度を調整
        digit = 2
        limit_price = round(limit_price, digit)

        # 希望注文額から数量を計算
        buy_amount = amountByUSDT / limit_price
        buy_amount = round(buy_amount, digit)

        # 精度調整後に注文額が1USDT未満になる場合、1USDTを超える最小値に調整
        order_value = buy_amount * limit_price
        if order_value < 1:
            # 1USDTを超える最小の数量を計算
            buy_amount = round(1 / limit_price, digit)
            # 丸めた結果がまだ1未満の場合、最小単位ずつ増やす
            min_increment = 10 ** (-digit)  # digit=3なら0.001、digit=2なら0.01
            while buy_amount * limit_price < 1:
                buy_amount = round(buy_amount + min_increment, digit)

        print(
            f"Place spot buy order : symbol={symbol}, amount={buy_amount}, price={limit_price}, order_value={buy_amount * limit_price:.2f} USDT")
        order = self.exchange.create_order(
            symbol=symbol,
            type='limit',
            side='buy',
            amount=buy_amount,
            price=limit_price,
            params={}
        )

        return order
