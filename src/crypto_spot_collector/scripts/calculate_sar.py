#!/usr/bin /env python3
"""Calculate SAR (Parabolic Stop and Reverse) and create charts"""


from datetime import datetime, timedelta
from io import BytesIO

import matplotlib.dates as mdates
import pandas as pd
from matplotlib import pyplot as plt
from ta.trend import PSARIndicator

from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository

webhook_url: str = (
    "https://discord.com/api/webhooks/1126667309612793907/"
    "uEnoqjxaAk7ZHdNDFVnJaVtfpwSalKf2FEZrB_T1XX4T7HAKMkueISJjb5tztJ3eb1pp"
)


async def main() -> None:
    """Main class for SAR calculation script."""

    endDate = datetime(2025, 10, 26)
    startDate = endDate - timedelta(days=21)

    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol="BTC",
            interval="4h",
            from_datetime=startDate,
            to_datetime=endDate
        )

        # データをDataFrameに変換
        df = pd.DataFrame([
            {
                'timestamp': d.timestamp_utc + timedelta(hours=9),  # JSTに変換
                'open': float(d.open_price),
                'high': float(d.high_price),
                'low': float(d.low_price),
                'close': float(d.close_price),
                'volume': float(d.volume)
            }
            for d in data
        ])

        # SAR計算（初期AF=0.02, 最大AF=0.2）
        sar_indicator = PSARIndicator(
            high=df['high'],
            low=df['low'],
            close=df['close'],
            step=0.02,
            max_step=0.2
        )

        df['sar'] = sar_indicator.psar()
        df['sar_up'] = sar_indicator.psar_up()
        df['sar_down'] = sar_indicator.psar_down()

        # データからグラフ作成
        fig, ax1 = plt.subplots(1, 1, figsize=(12, 8))

        # 価格チャート
        ax1.plot(
            df['timestamp'],
            df['close'],
            label="Close Price",
            color='blue',
            linewidth=2
        )

        # SARをドットで表示（トレンド転換で色を変更）
        sar_up_mask = ~pd.isna(df['sar_up'])
        sar_down_mask = ~pd.isna(df['sar_down'])

        # 上昇トレンド時のSAR（緑色）
        ax1.scatter(
            df.loc[sar_up_mask, 'timestamp'],
            df.loc[sar_up_mask, 'sar_up'],
            color='green',
            s=30,
            label='SAR (Bullish)',
            alpha=0.8
        )

        # 下降トレンド時のSAR（赤色）
        ax1.scatter(
            df.loc[sar_down_mask, 'timestamp'],
            df.loc[sar_down_mask, 'sar_down'],
            color='red',
            s=30,
            label='SAR (Bearish)',
            alpha=0.8
        )

        # ax1.axhline(100000, color='green', ls='--')

        ax1.grid(True, alpha=0.3)
        ax1.set_title("BTC Price with Parabolic SAR (4h)")
        ax1.set_ylabel("Price (USD)")
        ax1.legend()

        # 日付ラベルの重なりを防ぐ
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        ax1.xaxis.set_major_locator(mdates.HourLocator(interval=12))

        plt.xticks(rotation=45)
        plt.tight_layout()

        # 画像をメモリ上に保存
        img_buffer1 = BytesIO()
        plt.savefig(img_buffer1, format='png', dpi=150, bbox_inches='tight')
        img_buffer1.seek(0)

        notificator: discordNotification = discordNotification(webhook_url)

        # 画像を送信
        image_buffers = [
            (img_buffer1, "btc_price_sar.png"),
        ]
        await notificator.send_notification_with_image_async(
            "BTC価格とSAR", image_buffers
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
