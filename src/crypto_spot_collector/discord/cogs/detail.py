from datetime import datetime, timedelta
from io import BytesIO
from typing import List

import discord
import matplotlib.dates as mdates
import pandas as pd
from discord import app_commands
from discord.ext import commands
from loguru import logger
from matplotlib import pyplot as plt
from ta.trend import PSARIndicator

from crypto_spot_collector.apps.buy_spot import spot_symbol
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.dataframe import append_dates_with_nearest

auto_complete_symbols = [symbol.upper() for symbol in spot_symbol]
auto_complete_symbols.sort()


class DetailBybitCog(commands.Cog):
    def __init__(self, bot: commands.Bot, exchange: BybitExchange) -> None:
        self.bot = bot
        self.exchange = exchange

        logger.debug("DetailBybitCog initialized.")
        logger.debug(f"Auto-complete symbols: {auto_complete_symbols}")

    async def rps_autocomplete(self,
                               interaction: discord.Interaction,
                               current: str,
                               ) -> List[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=choice, value=choice)
            for choice in auto_complete_symbols if current.lower() in choice.lower()
        ]

    @app_commands.command(name="detail", description="Gets detailed profit and loss information.")
    @app_commands.autocomplete(symbol=rps_autocomplete)
    async def detail(self, interaction: discord.Interaction, symbol: str) -> None:
        """Detailed PnL command - to be implemented"""
        await interaction.response.defer()

        try:

            detail_image = create_detail(symbol)

            await interaction.followup.send("Here is the detailed chart:",
                                            file=discord.File(detail_image, filename=f"{symbol}_detail.png"))
        except Exception as e:
            logger.error(f"Error in Detail command: {e}")
            await interaction.followup.send("An error occurred while generating the detailed chart.")


async def setup(bot: commands.Bot) -> None:
    bybit_exchange = bot.bybit_exchange  # type: ignore
    await bot.add_cog(DetailBybitCog(bot, bybit_exchange))


def create_detail(symbol: str) -> BytesIO:
    endDate = datetime.now()
    startDate = endDate - timedelta(days=35)

    with OHLCVRepository() as repo:
        data = repo.get_ohlcv_data(
            symbol=symbol,
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

    with TradeDataRepository() as repo:
        buy_trades = repo.get_closed_long_positions_date(
            symbol=symbol,
            start_date=startDate,
            end_date=endDate
        )
        sell_trades = repo.get_closed_short_positions_date(
            symbol=symbol,
            start_date=startDate,
            end_date=endDate
        )

        buy_dates = [trade.timestamp_utc for trade in buy_trades]
        sell_dates = [trade.timestamp_utc for trade in sell_trades]

        average_price = repo.get_average_buy_price_by_symbol(symbol=symbol)

        df = append_dates_with_nearest(df, "buy_date", buy_dates)
        df = append_dates_with_nearest(df, "sell_date", sell_dates)

    # 表示範囲を最新データから7日間に制限（SARの計算前に実行）
    latest_date = df['timestamp'].max()
    start_display_date = latest_date - timedelta(days=14)
    df = df[df['timestamp'] >= start_display_date]

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

    # ロングした日時をグラフに反映
    buy_signal_data = df.loc[df['buy_date'].notna()]
    ax1.scatter(
        buy_signal_data['timestamp'],
        buy_signal_data['close'],
        color="#7CFF82",  # 落ち着いたグリーン
        s=100,
        label='Buy',
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
        label='Sell',
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

    # 平均価格
    ax1.axhline(average_price, color='green', ls='--', lw=1,
                alpha=0.7, label='Average Buy Price')
    ax1.text(df['timestamp'].iloc[0], average_price,
             f" Average Buy : {average_price:.2f}",
             va="bottom", ha="left", fontsize=9)

    ax1.grid(True, alpha=0.3, linestyle='--', linewidth=0.8)
    ax1.set_title(f"{symbol} Price with Parabolic SAR (1h)",
                  fontsize=18, fontweight='bold', pad=20,
                  color='#2C3E50')
    ax1.set_ylabel("Price (USD)", fontsize=13, fontweight='bold')
    ax1.set_xlabel("Date", fontsize=13, fontweight='bold')

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

    # 日付ラベルの重なりを防ぐ
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=12))

    plt.xticks(rotation=45)
    plt.tight_layout()

    # グラフをいったん保存
    img_buffer1 = BytesIO()
    plt.savefig(img_buffer1, format='png', dpi=150, bbox_inches='tight')
    img_buffer1.seek(0)
    plt.close()

    return img_buffer1
