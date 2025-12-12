

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def close_position_notification_message(
    close_date_utc: datetime,
    symbol: str,
    direction: str,
    pnl: float,
    fee: float,
    feeToken: str = "USDC",
) -> str:
    """ ポジションクローズの通知メッセージを生成するヘルパー関数 """

    close_date_utc = close_date_utc.astimezone(JST)
    time_str = close_date_utc.strftime("%Y/%m/%d %H:%M:%S")

    notification_message = f"{time_str:<20} {symbol} {direction} | PnL: {pnl:+.3f} USDC (Fee: {fee:.3f} {feeToken})"

    return notification_message


if __name__ == "__main__":
    message = close_position_notification_message(
        close_date_utc=datetime.now(timezone.utc),
        symbol="BTC/USDC:USDC",
        direction="Close Long",
        pnl=12.345,
        fee=0.123,
    )
    print(message)
