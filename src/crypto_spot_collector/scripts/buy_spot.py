from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import matplotlib.dates as mdates
import pandas as pd
from matplotlib import pyplot as plt
from ta.trend import PSARIndicator

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository
from crypto_spot_collector.scripts.import_historical_data import HistoricalDataImporter

spot_symbol = ["btc", "eth", "xrp", "sol", "avax"]

webhook_url: str = (
    "https://discord.com/api/webhooks/1126667309612793907/"
    "uEnoqjxaAk7ZHdNDFVnJaVtfpwSalKf2FEZrB_T1XX4T7HAKMkueISJjb5tztJ3eb1pp"
)

notificator = discordNotification(webhook_url)
importer = HistoricalDataImporter()

amountByUSDT = 1


def load_secrets() -> Any:
    import json
    from pathlib import Path

    secrets_path = Path(__file__).parent / "secrets.json"
    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    return secrets


secrets = load_secrets()


bybit_exchange = BybitExchange(
    apiKey=secrets["bybit"]["apiKey"], secret=secrets["bybit"]["secret"]
)


async def main() -> None:
    # 毎時0分に実行
    while True:
        # 1h足の取得・登録
        toDateUtc = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        fromDateUtc = toDateUtc - timedelta(days=1)

        # 過去1日のOHLCVデータを取得して登録
        for symbol in spot_symbol:
            ohlcv = bybit_exchange.fetch_ohlcv(
                symbol=f"{symbol.upper()}/USDT",
                timeframe="1h",
                fromDate=fromDateUtc,
                toDate=toDateUtc,
            )

            # OHLCVデータの登録
            importer.register_data(symbol.upper(), ohlcv)

        # 現時刻が1h足の区切り目であれば1h足の取得・登録・シグナルチェックも実行
        if toDateUtc.hour % 1 == 0:
            checkEndDate = toDateUtc
            checkStartDate = checkEndDate - timedelta(days=21)

            for symbol in spot_symbol:
                await check_signal(
                    startDate=checkStartDate,
                    endDate=checkEndDate,
                    symbol=symbol.upper(),
                    timeframe="1h"
                )

        # 待機処理
        now = datetime.now(timezone.utc)
        print(now)
        next_run = (now + timedelta(hours=1)).replace(minute=0,
                                                      second=0, microsecond=0)
        wait_seconds = (next_run - now).total_seconds()
        print(
            f"Waiting for {wait_seconds} seconds until next run at {next_run} UTC")
        await asyncio.sleep(wait_seconds)

    # await calculate_and_plot_sar()

    test_date_start = datetime(2025, 9, 1)
    test_iterations = 120

    for i in range(test_iterations):
        test_date = test_date_start + timedelta(hours=4 * i)
        print(f"=== Checking signal for {test_date} UTC ===")
        endDate = test_date
        startDate = endDate - timedelta(days=21)

        # await check_signal(startDate=startDate,
        #                    endDate=endDate,
        #                    symbol="BTC")

        # await check_signal(startDate=startDate,
        #                    endDate=endDate,
        #                    symbol="XRP")

        await check_signal(startDate=startDate, endDate=endDate, symbol="SOL")


async def check_signal(startDate: datetime, endDate: datetime, symbol: str, timeframe: str) -> None:
    """Check for SAR buy/sell signals and send Discord notification if detected."""

    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol=symbol, interval=timeframe, from_datetime=startDate, to_datetime=endDate
        )

        # データをDataFrameに変換
        df = pd.DataFrame(
            [
                {
                    "timestamp": d.timestamp_utc,  # JSTに変換
                    "open": float(d.open_price),
                    "high": float(d.high_price),
                    "low": float(d.low_price),
                    "close": float(d.close_price),
                    "volume": float(d.volume),
                }
                for d in data
            ]
        )

        # SAR計算（初期AF=0.02, 最大AF=0.2）
        sar_indicator = PSARIndicator(
            high=df["high"], low=df["low"], close=df["close"], step=0.02, max_step=0.2
        )

        df["sar"] = sar_indicator.psar()
        df["sar_up"] = sar_indicator.psar_up()
        df["sar_down"] = sar_indicator.psar_down()

        # SAR上昇シグナルをチェック
        sar_up_signal = check_sar_signal(df["sar_up"])
        print(f"SAR Up Signal: {sar_up_signal}")

        # デバッグ用：実際の値を表示
        print("Recent SAR Up values (newest first):")
        if sar_up_signal:
            try:
                bybit_exchange.create_order_spot(
                    amountByUSDT=amountByUSDT,
                    symbol=symbol
                )
            except Exception as e:
                print(f"Error creating spot order for {symbol}: {e}")
                await notificator.send_notification_async(
                    message=f"Error creating spot order for {symbol}: {e}"
                )
                return

            # Discord通知
            message = f"SAR Buy Signal detected for {symbol} at {endDate} UTC"

            # グラフ作成
            plot_buf = [(notification_plot_buff(
                df, symbol), f"{symbol}_sar.png")]
            await notificator.send_notification_with_image_async(
                message=message, image_buffers=plot_buf
            )

            for i, sar_up in enumerate(df["sar_up"].tail(10)[::-1]):
                print(f"  {i}: {sar_up}")
        else:
            print("No SAR Up signal detected.")


def check_sar_signal(sar_series: pd.Series) -> bool:
    """
    NaNから数値に切り替わって、そこから3つ連続で正の値になっている場合のみTrueを返す
    それ以上のプラス連続はFalseを返す
    """
    # 最新10件を逆順で取得(最新 -> 古い順)
    recent_values = sar_series.tail(10)[::-1].values

    consecutive_positive = 0

    # 最初に連続する数値の個数を数える
    for i, value in enumerate(recent_values):
        if pd.isna(value):
            break
        consecutive_positive += 1

    # 連続する数値が3つ以外の場合はFalse
    if consecutive_positive != 3:
        return False

    # 3つの数値の後にNaNがあるかチェック
    if consecutive_positive < len(recent_values) and pd.isna(
        recent_values[consecutive_positive]
    ):
        return True

    return False


def notification_plot_buff(df: pd.DataFrame, symbol: str) -> BytesIO:
    fig, ax1 = plt.subplots(1, 1, figsize=(12, 8))
    # 価格チャート
    ax1.plot(
        df["timestamp"], df["close"], label="Close Price", color="blue", linewidth=2
    )

    # SARをドットで表示（トレンド転換で色を変更）
    sar_up_mask = ~pd.isna(df["sar_up"])
    sar_down_mask = ~pd.isna(df["sar_down"])

    # 上昇トレンド時のSAR（緑色）
    ax1.scatter(
        df.loc[sar_up_mask, "timestamp"],
        df.loc[sar_up_mask, "sar_up"],
        color="green",
        s=30,
        label="SAR (Bullish)",
        alpha=0.8,
    )

    # 下降トレンド時のSAR（赤色）
    ax1.scatter(
        df.loc[sar_down_mask, "timestamp"],
        df.loc[sar_down_mask, "sar_down"],
        color="red",
        s=30,
        label="SAR (Bearish)",
        alpha=0.8,
    )

    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"{symbol} Price with Parabolic SAR (4h)")
    ax1.set_ylabel("Price (USD)")
    ax1.legend()

    # 日付ラベルの重なりを防ぐ
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=12))

    plt.xticks(rotation=45)
    plt.tight_layout()

    # 画像をメモリ上に保存
    img_buffer1 = BytesIO()
    plt.savefig(img_buffer1, format="png", dpi=150, bbox_inches="tight")
    img_buffer1.seek(0)

    return img_buffer1


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
