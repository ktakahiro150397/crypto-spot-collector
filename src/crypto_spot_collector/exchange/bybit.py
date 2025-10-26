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

    def create_order_spot(self, amountByUSDT: float, symbol: str) -> dict[Any, Any]:
        symbol = "XRP/USDT"

        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = self.fetch_price(symbol)
        buy_amount = amountByUSDT / current_price
        limit_price = current_price * 1.01  # 1%高い価格で指値買い

        print(
            f"Place spot buy order : symbol={symbol}, amount={buy_amount}, price={limit_price}")
        order = self.exchange.create_order(
            symbol=symbol,
            type='limit',
            side='buy',
            amount=buy_amount,
            price=limit_price,
            params={}
        )

        return order
