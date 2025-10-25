from typing import Any

import ccxt

# bybit.enable_demo_trading(enable=True)


class BybitExchange():
    def __init__(self, apiKey: str, secret: str) -> None:
        self.exchange = ccxt.bybit({
            'apiKey': apiKey,
            "secret": secret,
        })

    def fetch_balance(self) -> dict[Any, Any]:
        return self.exchange.fetch_balance()

    def create_order_spot(self) -> dict[Any, Any]:
        limit_price = 1
        symbol = "XRP/USDT"
        amount = 1

        order = self.exchange.create_order(
            symbol=symbol,
            type='limit',
            side='buy',
            amount=amount,
            price=limit_price,
            params={}
        )

        return order
