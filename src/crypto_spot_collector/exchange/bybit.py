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
    price: float  # 実際に注文した価格
    order_value: float  # 注文総額 (amount * price)
    original_order: Any  # 元のorder情報


@dataclass
class SpotAsset:
    """スポット資産の情報を格納するクラス"""

    symbol: str
    total_amount: float  # 総数量
    current_value: float  # 現在価値
    profit_loss: float  # 損益


@dataclass
class SpotSellResult:
    """スポット売却の結果を格納するクラス"""

    order_id: str
    symbol: str
    amount: float  # 実際に売却した数量
    price: float  # 実際に売却した価格
    order_value: float  # 売却総額 (amount * price)
    profit_loss: float  # 損益 (PnL)
    original_order: Any  # 元のorder情報


class BybitExchange:
    def __init__(self, apiKey: str, secret: str) -> None:
        logger.info("Initializing Bybit exchange client")
        self.exchange = ccxt.bybit(
            {
                "apiKey": apiKey,
                "secret": secret,
            }
        )
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
        """ """
        logger.debug(f"Fetching price for {symbol}")
        ticker: dict[Any, Any] = self.exchange.fetch_ticker(symbol)
        if "last" in ticker:
            logger.debug(f"Price for {symbol}: {ticker['last']}")
            return ticker
        else:
            logger.error(f"Price not found for symbol {symbol}")
            raise Exception(f"symbol = {symbol} | Price not found in ticker data")

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, fromDate: datetime, toDate: datetime
    ) -> dict[Any, Any]:
        logger.debug(
            f"Fetching OHLCV data for {symbol} ({timeframe}) from {fromDate} to {toDate}"
        )
        ohlcv: dict[Any, Any] = self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            since=int(fromDate.timestamp() * 1000),
            params={"until": int(toDate.timestamp() * 1000)},
            limit=1000,
        )
        if ohlcv:
            logger.debug(f"OHLCV data fetched for {symbol}: {len(ohlcv)} records")
            return ohlcv
        else:
            logger.error(f"OHLCV data not found for symbol {symbol}")
            raise Exception(f"symbol = {symbol} | OHLCV data not found")

    def fetch_currency(self) -> dict[Any, Any]:
        logger.debug("Fetching currency data")
        currency: dict[Any, Any] = self.exchange.fetch_currencies()
        if currency:
            logger.debug(f"Currency data fetched: {len(currency)} currencies")
            return currency
        else:
            logger.error("Currency data not found")
            raise Exception("Currency data not found")

    def create_order_spot(
        self, amountByUSDT: float, symbol: str
    ) -> tuple[Any, SpotOrderResult]:
        logger.info(f"Creating spot order for {symbol} with {amountByUSDT} USDT")

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
            f"Using amount precision: {amount_digit}, price precision: {price_digit} for {symbol}"
        )

        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        current_price = self.fetch_price(symbol)["last"]
        limit_price = current_price * 0.995  # 0.5%安い価格で指値買い
        limit_price = round(limit_price, price_digit)

        logger.debug(f"Current price: {current_price}, Limit price: {limit_price}")

        # 希望注文額から数量を計算
        buy_amount = amountByUSDT / limit_price
        buy_amount = round(buy_amount, amount_digit)

        # 精度調整後に注文額が1USDT未満になる場合、1USDTを超える最小値に調整
        order_value = buy_amount * limit_price
        if order_value < 1:
            logger.debug(f"Order value {order_value} < 1 USDT, adjusting amount")
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
            f"Placing spot buy order: symbol={symbol}, amount={buy_amount}, price={limit_price}, order_value={final_order_value:.2f} USDT"
        )

        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side="buy",
                amount=buy_amount,
                price=limit_price,
                params={},
            )
            logger.success(
                f"Spot order created successfully for {symbol}: Order ID {order.get('id', 'N/A')}"
            )

            # 結果をSpotOrderResultクラスにまとめる
            result = SpotOrderResult(
                order_id=order.get("id", "N/A"),
                symbol=symbol,
                amount=buy_amount,
                price=limit_price,
                order_value=final_order_value,
                original_order=order,
            )

            return order, result

        except Exception as e:
            logger.error(f"Failed to create spot order for {symbol}: {e}")
            raise

    def sell_spot(self, symbol: str, amount: float) -> tuple[Any, SpotSellResult]:
        """
        指定のシンボルの現物を売却し、結果を返す関数

        Args:
            symbol: 売却する通貨シンボル (例: "BTC", "ETH")
            amount: 売却する数量

        Returns:
            tuple[Any, SpotSellResult]: (元のorder情報, 売却結果)
            売却結果には売却価格、売却数量、PnLが含まれる
        """
        logger.info(f"Selling spot: {amount} {symbol}")

        # シンボルの形式を統一
        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"

        # 現在価格を取得
        current_price = self.fetch_price(symbol)["last"]
        logger.debug(f"Current price for {symbol}: {current_price}")

        # 平均買付価格を取得してPnLを計算
        average_buy_price = 0.0
        pnl = 0.0
        try:
            average_buy_price = self.fetch_average_buy_price_spot(symbol.split("/")[0])
            if average_buy_price > 0:
                pnl = round((current_price - average_buy_price) * amount, 5)
            else:
                logger.warning(f"No average buy price found for {symbol}, PnL set to 0")
        except Exception as e:
            logger.warning(
                f"Failed to calculate PnL for {symbol}: {e}, setting PnL to 0"
            )

        logger.debug(f"Calculated PnL: {pnl} USDT")

        # 売却額を計算
        sell_value = amount * current_price

        logger.info(
            f"Placing market sell order: symbol={symbol}, amount={amount}, estimated_value={sell_value:.2f} USDT"
        )

        try:
            order = self.exchange.create_order(
                symbol=symbol, type="market", side="sell", amount=amount, params={}
            )
            logger.success(
                f"Spot sell order created successfully for {symbol}: Order ID {order.get('id', 'N/A')}"
            )

            # 実際の約定価格と数量を取得
            filled_price = order.get(
                "average", current_price
            )  # 約定価格（なければ現在価格）
            filled_amount = order.get("filled", amount)  # 約定数量（なければ指定数量）
            actual_value = filled_price * filled_amount

            # PnLを実際の約定数量で再計算
            if average_buy_price > 0:
                pnl = round((filled_price - average_buy_price) * filled_amount, 5)

            # 結果をSpotSellResultクラスにまとめる
            result = SpotSellResult(
                order_id=order.get("id", "N/A"),
                symbol=symbol,
                amount=filled_amount,
                price=filled_price,
                order_value=actual_value,
                profit_loss=pnl,
                original_order=order,
            )

            logger.info(
                f"Sell order completed: price={filled_price}, amount={filled_amount}, value={actual_value:.2f} USDT, PnL={pnl:.2f} USDT"
            )

            return order, result

        except Exception as e:
            logger.error(f"Failed to create spot sell order for {symbol}: {e}")
            raise

    def fetch_average_buy_price_spot(self, symbol: str) -> float:
        logger.debug(f"Fetching average buy price for {symbol} spot")
        try:
            orders = self.exchange.fetch_closed_orders(
                symbol=f"{symbol}/USDT", since=None, limit=100, params={}
            )
            buy_orders = [
                order
                for order in orders
                if order["side"] == "buy" and order["status"] == "closed"
            ]
            total_cost = sum(float(order["cost"]) for order in buy_orders)
            total_amount = sum(float(order["amount"]) for order in buy_orders)

            if total_amount == 0:
                logger.warning(f"No completed buy orders found for {symbol} spot")
                return 0.0

            logger.debug(f"Total cost: {total_cost}, Total amount: {total_amount}")

            average_price = total_cost / total_amount
            logger.info(f"Average buy price for {symbol} spot: {average_price}")
            return average_price

        except Exception as e:
            logger.error(f"Failed to fetch average buy price for {symbol} spot: {e}")
            raise

    def get_current_spot_pnl(self, symbol: str) -> float:
        try:
            orders = self.exchange.fetch_closed_orders(
                symbol=f"{symbol}/USDT", since=None, limit=100, params={}
            )
            buy_orders = [
                order
                for order in orders
                if order["side"] == "buy" and order["status"] == "closed"
            ]
            total_cost = sum(float(order["cost"]) for order in buy_orders)
            total_amount = sum(float(order["amount"]) for order in buy_orders)

            if total_amount == 0:
                logger.warning(f"No completed buy orders found for {symbol} spot")
                return 0.0

            logger.debug(f"Total cost: {total_cost}, Total amount: {total_amount}")

            average_price = total_cost / total_amount
            logger.info(f"Average buy price for {symbol} spot: {average_price}")

            current_price = self.fetch_price(f"{symbol}/USDT")["last"]
            pnl = round((current_price - average_price) * total_amount, 5)
            logger.info(
                f"Current PnL for {symbol} spot: {pnl} (Current Price: {current_price})"
            )

            return float(pnl)
        except Exception as e:
            logger.error(f"Failed to fetch average buy price for {symbol} spot: {e}")
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
                    current_value = (
                        self.fetch_price(f"{coin['coin']}/USDT")["last"] * equity
                    )

                spot_asset = SpotAsset(
                    symbol=coin["coin"],
                    total_amount=equity,
                    current_value=current_value,
                    profit_loss=pnl,
                )
                portfolio.append(spot_asset)

        # USDTを先頭に移動
        portfolio.sort(key=lambda x: (x.symbol != "USDT", x.symbol))

        logger.info("Spot portfolio fetched.")
        return portfolio
