

from datetime import datetime
from typing import Any

from loguru import logger

from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository


def create_update_trade_data(
    symbol: str,
    open_trades: list[Any],
    closed_trades: list[Any],
    canceled_trades: list[Any]
) -> None:
    logger.debug(
        f"Total {len(closed_trades)} trade records fetched for {symbol.upper()}.")
    logger.debug(
        f"Total {len(open_trades)} open trade records fetched for {symbol.upper()}.")
    logger.debug(
        f"Total {len(canceled_trades)} canceled trade records fetched for {symbol.upper()}.")

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

        for trade in canceled_trades:
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
                fee=0,  # キャンセルされたトレードのfeeは0
                timestamp_utc=timestamp_datetime,
            )
