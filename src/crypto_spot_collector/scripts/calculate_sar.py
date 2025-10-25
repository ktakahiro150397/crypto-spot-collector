#!/usr/bin /env python3
"""Buy spot with historical data"""


from datetime import datetime, timedelta
from io import BytesIO

import matplotlib.dates as mdates
from matplotlib import pyplot as plt

from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository

webhook_url: str = (
    "https://discord.com/api/webhooks/1126667309612793907/"
    "uEnoqjxaAk7ZHdNDFVnJaVtfpwSalKf2FEZrB_T1XX4T7HAKMkueISJjb5tztJ3eb1pp"
)


async def main() -> None:
    """Main class for SAR calculation script."""

    startDate = datetime(2025, 10, 1)
    endDate = startDate + timedelta(days=14)

    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol="BTC",
            interval="4h",
            from_datetime=startDate,
            to_datetime=endDate
        )

        # データからグラフ作成
        fig, ax1 = plt.subplots(1, 1, figsize=(12, 8))

        # 価格チャート
        ax1.plot(
            [d.timestamp_utc for d in data],
            [d.close_price for d in data],
            label="Close Price"
        )
        ax1.grid()
        ax1.set_title("BTC Close Price (4h)")
        ax1.set_ylabel("Price (USD)")
        ax1.legend()

        # 日付ラベルの重なりを防ぐ
        for ax in [ax1]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))

        plt.xticks(rotation=45)
        plt.tight_layout()

        # 1つ目の画像（価格+出来高）をメモリ上に保存
        img_buffer1 = BytesIO()
        plt.savefig(img_buffer1, format='png', dpi=150, bbox_inches='tight')
        img_buffer1.seek(0)

        notificator: discordNotification = discordNotification(webhook_url)

        # 複数画像を送信
        image_buffers = [
            (img_buffer1, "btc_price_detailed.png"),
        ]
        await notificator.send_notification_with_image_async(
            "BTC価格チャート（価格+出来高、価格詳細）", image_buffers
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
