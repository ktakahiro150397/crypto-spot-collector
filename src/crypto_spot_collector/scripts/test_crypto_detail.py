#!/usr/bin /env python3
"""Calculate SAR (Parabolic Stop and Reverse) and create charts"""
import random
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
import seaborn as sns
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from PIL import Image
from ta.trend import PSARIndicator

from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.dataframe import append_dates_with_nearest

# from ..models import TradeData

# ライトテーマでいい感じのスタイルを設定
sns.set_style("whitegrid")
sns.set_palette("husl")

# カスタムTTFフォントを使用する設定
# 使い方: fontsフォルダにTTFファイルを配置して、ファイル名を指定
# 例: "fonts/Inter-Regular.ttf" or "fonts/Roboto-Regular.ttf"
CUSTOM_FONT_PATH = Path(
    __file__).parent / "font" / "CourierPrime-Regular.ttf"

if CUSTOM_FONT_PATH and Path(CUSTOM_FONT_PATH).exists():
    # TTFファイルを登録
    font_manager.fontManager.addfont(CUSTOM_FONT_PATH)
    custom_font = font_manager.FontProperties(fname=CUSTOM_FONT_PATH)
    plt.rcParams['font.family'] = custom_font.get_name()
    print(f"カスタムフォントを使用: {custom_font.get_name()}")
else:
    # デフォルトフォント（システムフォント）
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
    if CUSTOM_FONT_PATH:
        print(f"警告: {CUSTOM_FONT_PATH} が見つかりません。デフォルトフォントを使用します。")

plt.rcParams['font.size'] = 11

# ライトテーマの配色
plt.rcParams['figure.facecolor'] = '#FFFFFF'
plt.rcParams['axes.facecolor'] = '#F8F9FA'
plt.rcParams['axes.edgecolor'] = '#CCCCCC'
plt.rcParams['grid.color'] = '#E0E0E0'
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['grid.linewidth'] = 0.8
plt.rcParams['text.color'] = '#2C3E50'
plt.rcParams['axes.labelcolor'] = '#2C3E50'
plt.rcParams['xtick.color'] = '#2C3E50'
plt.rcParams['ytick.color'] = '#2C3E50'

webhook_url: str = (
    "https://discord.com/api/webhooks/1126667309612793907/"
    "uEnoqjxaAk7ZHdNDFVnJaVtfpwSalKf2FEZrB_T1XX4T7HAKMkueISJjb5tztJ3eb1pp"
)


async def main() -> None:
    endDate = datetime(2025, 11, 14)
    startDate = endDate - timedelta(days=21)

    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol="XRP",
            interval="1h",
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
        # SMA50の計算
        df["sma_50"] = df['close'].rolling(window=50).mean()
        # SMA100の計算
        df["sma_100"] = df['close'].rolling(window=100).mean()

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

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values(by='timestamp')

    with TradeDataRepository() as repo:
        buy_trades: list[TradeData] = repo.get_closed_long_positions_date(
            symbol="XRP",
            start_date=startDate,
            end_date=endDate
        )
        buy_dates = [trade.timestamp_utc for trade in buy_trades]

        sell_trades: list[TradeData] = repo.get_closed_short_positions_date(
            symbol="XRP",
            start_date=startDate,
            end_date=endDate
        )
        sell_dates = [trade.timestamp_utc for trade in sell_trades]

        average_price = repo.get_average_buy_price_by_symbol(symbol="XRP")

        df = append_dates_with_nearest(df, "buy_date", buy_dates)
        df = append_dates_with_nearest(df, "sell_date", sell_dates)

    # 2週間分に制限
    latest_date = df['timestamp'].max()
    start_display_date = latest_date - timedelta(days=14)
    df = df[df['timestamp'] >= start_display_date]

    # データからグラフ作成
    fig, ax1 = plt.subplots(1, 1, figsize=(16, 9))

    # 価格チャート（ライトテーマ用配色）
    ax1.plot(
        df['timestamp'],
        df['close'],
        label="Close Price",
        color='#1E88E5',  # 落ち着いたブルー
        linewidth=2.5,
        zorder=3
    )

    # ロングした日時をグラフに反映（画像マーカーを使用）
    buy_signal_data = df.loc[df['buy_date'].notna()]
    # if len(buy_signal_data) > 0:
    #     # 使用する画像ファイルのパス（この例では購入アイコンのような画像を想定）
    #     # 例: アイコンフォントやPNG画像を配置してください
    #     image_path = Path(__file__).parent / "icon" / "hana_marker.webp"

    #     # 画像が存在する場合は画像マーカーを使用、そうでなければ通常のマーカー
    #     if image_path.exists():
    #         # 画像を読み込み
    #         img = plt.imread(image_path)

    #         # 画像の横幅を基準にズーム値を自動調整
    #         target_width_pixels = 100  # 目標の横幅（ピクセル）
    #         img_width = img.shape[1]  # 画像の実際の横幅
    #         zoom = target_width_pixels / img_width

    #         imagebox = OffsetImage(img, zoom=zoom)  # 自動調整されたzoomを使用

    #         for _, row in buy_signal_data.iterrows():
    #             # 画像の位置調整（オフセット）
    #             offset_x = -30  # X方向のオフセット（時間軸方向）
    #             offset_y = -20  # Y方向のオフセット（価格軸方向）

    #             ab = AnnotationBbox(
    #                 imagebox,
    #                 (row['timestamp'], row['close']),
    #                 xybox=(offset_x, offset_y),  # オフセット指定
    #                 xycoords='data',  # 基準座標系
    #                 boxcoords='offset points',  # オフセットの単位（ポイント）
    #                 frameon=False,
    #                 pad=0
    #             )
    #             ax1.add_artist(ab)

    #         # 凡例用のダミープロット（画像は凡例に表示されないため）
    #         ax1.scatter([], [], color="#7CFF82", s=100, label='Buy Signal',
    #                     marker='^', alpha=0.9)

    # 通常のマーカーを使用
    ax1.scatter(
        buy_signal_data['timestamp'],
        buy_signal_data['close'],
        color="#7CFF82",  # 落ち着いたグリーン
        s=100,
        label='Buy Signal',
        marker='^',
        alpha=0.9,
        edgecolors='#2E7D32',
        linewidths=1.5,
        zorder=5
    )

    sell_signal_data = df.loc[df['sell_date'].notna()]
    ax1.scatter(
        sell_signal_data['timestamp'],
        sell_signal_data['close'],
        color="#FF6E6E",  # ソフトなレッド
        s=100,
        label='Sell Signal',
        marker='v',
        alpha=0.9,
        edgecolors='#C62828',
        linewidths=1.5,
        zorder=5
    )

    # SARをドットで表示（トレンド転換で色を変更）
    sar_up_mask = ~pd.isna(df['sar_up'])
    sar_down_mask = ~pd.isna(df['sar_down'])

    # 上昇トレンド時のSAR（エメラルドグリーン）
    ax1.scatter(
        df.loc[sar_up_mask, 'timestamp'],
        df.loc[sar_up_mask, 'sar_up'],
        color='#26A69A',
        s=60,
        label='SAR (Bullish)',
        alpha=0.85,
        edgecolors='#1A7A6D',
        linewidths=1.2,
        zorder=4
    )

    # 下降トレンド時のSAR（コーラルレッド）
    ax1.scatter(
        df.loc[sar_down_mask, 'timestamp'],
        df.loc[sar_down_mask, 'sar_down'],
        color='#EF5350',
        s=60,
        label='SAR (Bearish)',
        alpha=0.85,
        edgecolors='#C62828',
        linewidths=1.2,
        zorder=4
    )
    # average_price = 106000
    ax1.axhline(average_price, color='green', ls='--', lw=1,
                alpha=0.7, label='Average Buy Price')
    # ax1.text(df['timestamp'].iloc[0], average_price,
    #          f" Average Buy : {average_price:.2f}",
    #          va="bottom", ha="left", fontsize=9)

    limit_price = 0
    if limit_price > 0:
        ax1.axhline(limit_price, color='green', ls="-", lw=1,
                    alpha=0.7, label='Limit Buy Price')
        # ax1.text(df['timestamp'].iloc[0], limit_price,
        #          f" Limit Buy : {limit_price:.2f}",
        #          va="bottom", ha="left", fontsize=9)

    ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.8)
    ax1.set_title("BTC Price with Parabolic SAR (4h)",
                  fontsize=18, fontweight='bold', pad=20,
                  color='#2C3E50')
    ax1.set_ylabel("Price (USD)", fontsize=13, fontweight='bold')
    ax1.set_xlabel("Date", fontsize=13, fontweight='bold')

    # SMA50（オレンジゴールド）
    ax1.plot(
        df['timestamp'],
        df['sma_50'],
        label="SMA 50",
        color='#FFA726',
        linewidth=2.2,
        alpha=0.85,
        linestyle='-',
        zorder=2
    )

    # SMA100（ディープパープル）
    ax1.plot(
        df['timestamp'],
        df['sma_100'],
        label="SMA 100",
        color='#7E57C2',
        linewidth=2.2,
        alpha=0.85,
        linestyle='-',
        zorder=2
    )

    # レジェンドをライトテーマでいい感じに
    ax1.legend(
        loc='upper left',
        framealpha=0.95,
        fancybox=True,
        shadow=True,
        fontsize=11,
        edgecolor='#CCCCCC',
        facecolor='white'
    )

    # # 表示範囲を最新データから7日間に制限
    # latest_date = df['timestamp'].max()
    # start_display_date = latest_date - timedelta(days=7)
    # ax1.set_xlim(start_display_date, latest_date)

    # 日付ラベルの重なりを防ぐ
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=12))

    plt.xticks(rotation=45)
    plt.tight_layout()

    # グラフをいったん保存
    # img_buffer1 = BytesIO()
    plt.savefig("test_crypto_detail.png", format='png',
                dpi=150, bbox_inches='tight')
    # img_buffer1.seek(0)
    plt.close()

    # # フォトフレーム画像と合成
    # frame_image_path = Path(
    #     __file__).parent / "pict" / "frame_shukishukidaishuki_wide.png"
    # if frame_image_path.exists():
    #     # グラフ画像を読み込み
    #     graph_img = Image.open(img_buffer1).convert("RGBA")
    #     graph_width, graph_height = graph_img.size

    #     # フレーム画像を読み込み
    #     frame_img = Image.open(frame_image_path).convert("RGBA")

    #     # フレームをグラフと同じサイズにリサイズ
    #     frame_resized = frame_img.resize(
    #         (graph_width, graph_height), Image.Resampling.LANCZOS)

    #     # グラフの上にフレームを重ねる
    #     # フレームを最前面に配置
    #     combined_img = Image.new('RGBA', (graph_width, graph_height))
    #     combined_img.paste(graph_img, (0, 0))
    #     combined_img.paste(frame_resized, (0, 0), frame_resized)

    #     # 合成画像をバッファに保存
    #     img_buffer1 = BytesIO()
    #     combined_img.save(img_buffer1, format='PNG')
    #     img_buffer1.seek(0)

    # notificator: discordNotification = discordNotification(webhook_url)

    # # 画像を送信
    # image_buffers = [
    #     (img_buffer1, "btc_price_sar.png"),
    # ]
    # await notificator.send_notification_with_image_async(
    #     "BTC価格とSAR", image_buffers
    # )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
