"""過去トレードデータをすべて取得してtrade_dataテーブルに挿入・更新するスクリプト。"""
import asyncio
from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.utils.secrets import load_config
from crypto_spot_collector.utils.trade_data import create_update_trade_data

secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

spot_symbol = ["btc", "eth", "xrp", "sol", "link",
               "avax", "hype", "bnb", "doge", "wld", "ltc", "pol",
               "xaut",]

# spot_symbol = ["doge"]


async def main() -> None:
    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )

    for symbol in spot_symbol:
        logger.info(f"Fetching all trade data for {symbol.upper()}...")

        # 過去トレードデータをすべて取得
        closed_trades = bybit_exchange.fetch_close_orders_all(
            symbol=symbol.upper())

        open_trades = bybit_exchange.fetch_open_orders_all(
            symbol=symbol.upper())

        canceled_trades = bybit_exchange.fetch_canceled_orders_all(
            symbol=symbol.upper())

        logger.info(
            f"Total {len(closed_trades)} trade records fetched for {symbol.upper()}.")
        logger.info(
            f"Total {len(open_trades)} open trade records fetched for {symbol.upper()}.")
        logger.info(
            f"Total {len(canceled_trades)} canceled trade records fetched for {symbol.upper()}.")

        create_update_trade_data(
            symbol=symbol,
            open_trades=open_trades,
            closed_trades=closed_trades,
            canceled_trades=canceled_trades
        )

if __name__ == "__main__":

    asyncio.run(main())
