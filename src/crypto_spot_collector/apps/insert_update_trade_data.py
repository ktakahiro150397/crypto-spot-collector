"""過去トレードデータをすべて取得してtrade_dataテーブルに挿入・更新するスクリプト。"""
import asyncio
from datetime import datetime
from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.secrets import load_config

secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

spot_symbol = ["btc", "eth", "xrp", "sol", "link",
               "avax", "hype", "bnb", "doge", "wld", "ltc", "pol",
               "xaut",]


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

        logger.info(
            f"Total {len(closed_trades)} trade records fetched for {symbol.upper()}.")

        open_trades = bybit_exchange.fetch_open_orders_all(
            symbol=symbol.upper())

        # ここでデータベースへの挿入・更新処理を行う
        with TradeDataRepository() as repo:
            for trade in closed_trades:
                # Unixタイムスタンプ（ミリ秒）をdatetimeオブジェクトに変換
                timestamp_ms = trade['timestamp']
                timestamp_datetime = datetime.fromtimestamp(
                    timestamp_ms / 1000)

                repo.create_or_update_trade_data(
                    cryptocurrency_name=symbol.upper(),
                    exchange_name="bybit",
                    trade_id=trade['id'],
                    status=trade['status'],
                    position_type=trade['side'],
                    is_spot=True,
                    leverage_ratio=1.00,
                    price=trade['price'],
                    quantity=trade['amount'],
                    fee=trade['fee']['cost'] * trade['price'],  # feeをUSDT換算
                    timestamp_utc=timestamp_datetime,
                )
            for trade in open_trades:
                # Unixタイムスタンプ（ミリ秒）をdatetimeオブジェクトに変換
                timestamp_ms = trade['timestamp']
                timestamp_datetime = datetime.fromtimestamp(
                    timestamp_ms / 1000)

                repo.create_or_update_trade_data(
                    cryptocurrency_name=symbol.upper(),
                    exchange_name="bybit",
                    trade_id=trade['id'],
                    status=trade['status'],
                    position_type=trade['side'],
                    is_spot=True,
                    leverage_ratio=1.00,
                    price=trade['price'],
                    quantity=trade['amount'],
                    fee=0,  # 未決済トレードのfeeは0
                    timestamp_utc=timestamp_datetime,
                )

if __name__ == "__main__":

    asyncio.run(main())
