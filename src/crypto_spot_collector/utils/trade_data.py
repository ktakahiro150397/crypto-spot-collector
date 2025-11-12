

from datetime import datetime
from typing import Any

from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange
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

            if trade['fee'] is None:
                fee = 0
            elif trade['fee']['currency'].upper() == 'USDT':
                fee = trade['fee']['cost']
            else:
                fee = trade['fee']['cost'] * trade['price']  # feeをUSDT換算

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
                fee=fee,  # feeをUSDT換算
                timestamp_utc=timestamp_datetime,
            )
        for trade in open_trades:
            # Unixタイムスタンプ（ミリ秒）をdatetimeオブジェクトに変換
            timestamp_ms = trade['timestamp']
            timestamp_datetime = datetime.fromtimestamp(
                timestamp_ms / 1000)

            if trade['fee'] is None:
                fee = 0
            elif trade['fee']['currency'].upper() == 'USDT':
                fee = trade['fee']['cost']
            else:
                fee = trade['fee']['cost'] * trade['price']  # feeをUSDT換算

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
                fee=fee,
                timestamp_utc=timestamp_datetime,
            )

        for trade in canceled_trades:
            # Unixタイムスタンプ（ミリ秒）をdatetimeオブジェクトに変換
            timestamp_ms = trade['timestamp']
            timestamp_datetime = datetime.fromtimestamp(
                timestamp_ms / 1000)

            if trade['fee'] is None:
                fee = 0
            elif trade['fee']['currency'].upper() == 'USDT':
                fee = trade['fee']['cost']
            else:
                fee = trade['fee']['cost'] * trade['price']  # feeをUSDT換算

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
                fee=fee,
                timestamp_utc=timestamp_datetime,
            )


def get_current_pnl_from_db(exchange: BybitExchange, symbol: str) -> float:
    """Calculate current PnL from the database trade data.

    Returns:
        float: Current profit and loss.
    """
    with TradeDataRepository() as repo:
        holdings, average_buy_price = repo.get_current_position_and_avg_price(
            symbol=symbol
        )

        current_price = float(exchange.fetch_price(
            symbol=f"{symbol.upper()}/USDT")["last"])

        pnl = (current_price - average_buy_price) * holdings

        return pnl

    return 0.0
