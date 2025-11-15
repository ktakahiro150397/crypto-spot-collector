from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO

import matplotlib.dates as mdates
import matplotlib.transforms as transforms
import pandas as pd
from loguru import logger
from matplotlib import pyplot as plt

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.dataframe import append_dates_with_nearest


@dataclass
class CreatePnlResult:
    img_buffer: BytesIO = BytesIO()
    total_current_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    df: pd.DataFrame = None


async def create_pnl_plot(exchange: BybitExchange,
                          tradeRepo: TradeDataRepository) -> CreatePnlResult:
    result = CreatePnlResult()

    portfolio = await exchange.get_spot_portfolio_async()
    for asset in portfolio:
        holdings, avg_price = tradeRepo.get_current_position_and_avg_price(
            symbol=asset.symbol
        )
        current_price = 1.0
        if asset.symbol != "USDT":
            current_price = float(
                (await exchange.fetch_price_async(
                    f"{asset.symbol}/USDT"))["last"]
            )
        asset.total_amount = holdings
        asset.current_value = holdings * current_price
        asset.profit_loss = asset.current_value - \
            (holdings * avg_price)
        # ROI calculation: (current_value - cost) / cost * 100
        cost = holdings * avg_price
        asset.roi_percent = (asset.profit_loss / cost *
                             100) if cost != 0 else 0

    if len(portfolio) == 0:
        raise ValueError("No assets in the portfolio.")

    logger.debug("Generating PnL statement chart")

    # サブプロットの作成
    column_count = 3
    non_usdt_count = len([e for e in portfolio if e.symbol != "USDT"])
    # +1 for the first row
    rows = non_usdt_count // column_count + \
        (non_usdt_count % column_count > 0) + 1
    fig, axes = plt.subplots(rows, column_count,
                             figsize=(12 * column_count, 8 * rows + 10))
    fig.suptitle('Cryptocurrency Portfolio Analysis', fontsize=16, y=0.995)

    df = pd.DataFrame(
        [
            {
                "Symbol": asset.symbol,
                "Total_Amount": asset.total_amount,
                "Current_Value": asset.current_value,
                "PnL": asset.profit_loss,
                "ROI%": asset.roi_percent,
                "Investment": asset.total_amount * tradeRepo.get_current_position_and_avg_price(asset.symbol)[1],
            }
            for asset in portfolio if asset.symbol != "USDT"
        ]
    )
    total_current_value = df['Current_Value'].sum()
    total_pnl = df['PnL'].sum()
    total_investment = df['Investment'].sum()
    total_pnl_percent = (total_pnl / (total_current_value - total_pnl)) * \
        100 if (total_current_value - total_pnl) != 0 else 0
    result.total_current_value = total_current_value
    result.total_pnl = total_pnl
    result.total_pnl_percent = total_pnl_percent
    result.df = df

    logger.debug(
        f"Total Investment: {total_investment}, Total Current Value: {total_current_value}, Total PnL: {total_pnl}({total_pnl_percent:+.2f}%)")

    logger.debug(
        f"Total Current Value: {total_current_value}, Total PnL: {total_pnl}({total_pnl_percent:+.2f}%)")

    # ---- 1行目 ----
    # 1. 現在価値の円グラフ(シンボルごと)
    axes[0, 0].pie(df['Current_Value'], labels=df['Symbol'],
                   autopct='%1.1f%%', startangle=140)
    axes[0, 0].set_title('Current Value Distribution by Asset')

    # 2. PnLの棒グラフ（正負で色分け）
    colors = ['green' if x >= 0 else 'red' for x in df['PnL']]
    axes[0, 1].bar(df['Symbol'], df['PnL'], color=colors)
    axes[0, 1].set_title('Profit & Loss by Asset')
    axes[0, 1].set_ylabel('PnL (USDT)')
    axes[0, 1].tick_params(axis='x', rotation=45)
    axes[0, 1].axhline(y=0, color='black', linestyle='-', alpha=0.3)

    # 3. 投資額 vs 現在価値の比較（グループ化棒グラフ）
    import numpy as np
    x = np.arange(len(df['Symbol']))
    width = 0.35

    bars1 = axes[0, 2].bar(x - width/2, df['Investment'], width,
                           label='Investment', color='#FFA726', alpha=0.8)
    bars2 = axes[0, 2].bar(x + width/2, df['Current_Value'], width,
                           label='Current Value', color='#42A5F5', alpha=0.8)

    axes[0, 2].set_title('Investment vs Current Value by Asset')
    axes[0, 2].set_ylabel('Amount (USDT)')
    axes[0, 2].set_xlabel('Asset')
    axes[0, 2].set_xticks(x)
    axes[0, 2].set_xticklabels(df['Symbol'], rotation=45)
    axes[0, 2].legend(loc='upper left')
    axes[0, 2].grid(True, alpha=0.3, axis='y')

    # 各バーの上に数値表示
    for bar in bars1:
        height = bar.get_height()
        axes[0, 2].text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}',
                        ha='center', va='bottom', fontsize=8)
    for bar in bars2:
        height = bar.get_height()
        axes[0, 2].text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}',
                        ha='center', va='bottom', fontsize=8)

    # ---- 2行目以降 ----
    timeframe = "1h"
    endDate = datetime.now(timezone.utc)
    startDate = endDate - timedelta(days=60)

    non_usdt_assets = [e for e in portfolio if e.symbol != "USDT"]
    for i, asset in enumerate(non_usdt_assets):
        symbol = asset.symbol

        # 2行目以降のインデックス計算 (1行目は別用途)
        row_idx = (i // column_count) + 1
        col_idx = i % column_count

        set_symbol_plot(
            tradeRepo=tradeRepo,
            timeframe=timeframe,
            symbol=symbol,
            startDate=startDate,
            endDate=endDate,
            axe=axes[row_idx, col_idx]
        )

    # 2行目以降の空白のサブプロットを非表示にする
    total_plots = len(non_usdt_assets)
    last_row = (total_plots // column_count) + 1
    filled_in_last_row = total_plots % column_count

    if filled_in_last_row > 0:
        for col in range(filled_in_last_row, column_count):
            axes[last_row, col].axis('off')

    # グラフ間の余白を調整
    plt.tight_layout(rect=(0, 0, 1, 0.99), h_pad=4.0, w_pad=3.0)

    # 画像をBytesIOに保存
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='PNG')
    img_buffer.seek(0)
    result.img_buffer = img_buffer
    plt.close()

    return result


def set_symbol_plot(tradeRepo: TradeDataRepository,
                    timeframe: str,
                    symbol: str,
                    startDate: datetime,
                    endDate: datetime,
                    axe: plt.Axes
                    ) -> None:
    # ---- 2行目以降 ----
    # timeframe = "1h"
    # symbol = "BTC"
    # endDate = datetime.now(timezone.utc)
    # startDate = endDate - timedelta(days=60)

    # チャート取得
    data_provider = MarketDataProvider()
    symbol_ohlcv_df = data_provider.get_dataframe_with_indicators(
        symbol=symbol,
        interval=timeframe,
        from_datetime=startDate,
        to_datetime=endDate,
        sma_windows=[50, 100],
        sar_config={"step": 0.02, "max_step": 0.2}
    )

    # トレードデータ取得
    buy_trades = tradeRepo.get_closed_long_positions_date(
        symbol=symbol,
        start_date=startDate,
        end_date=endDate
    )
    sell_trades = tradeRepo.get_closed_short_positions_date(
        symbol=symbol,
        start_date=startDate,
        end_date=endDate
    )

    buy_dates = [trade.timestamp_utc for trade in buy_trades]
    sell_dates = [trade.timestamp_utc for trade in sell_trades]

    # 平均取得価格
    average_price = tradeRepo.get_average_buy_price_by_symbol(symbol=symbol)

    symbol_ohlcv_df = append_dates_with_nearest(
        symbol_ohlcv_df, "buy_date", buy_dates)
    symbol_ohlcv_df = append_dates_with_nearest(
        symbol_ohlcv_df, "sell_date", sell_dates)

    # 表示範囲を最新データから14日間に制限
    latest_date = symbol_ohlcv_df['timestamp'].max()
    start_display_date = latest_date - timedelta(days=14)
    symbol_ohlcv_df = symbol_ohlcv_df[symbol_ohlcv_df['timestamp']
                                      >= start_display_date]

    # 価格チャート（ライトテーマ用配色）
    axe.plot(
        symbol_ohlcv_df['timestamp'],
        symbol_ohlcv_df['close'],
        label="Close Price",
        color='#1E88E5',  # 落ち着いたブルー
        linewidth=2.5,
        zorder=3
    )

    # ロングした日時をグラフに反映
    buy_signal_data = symbol_ohlcv_df.loc[symbol_ohlcv_df['buy_date'].notna()]
    # Y軸方向に-10ピクセルオフセット
    trans_offset = transforms.offset_copy(
        axe.transData, fig=axe.figure, y=-10, units='dots')
    axe.scatter(
        buy_signal_data['timestamp'],
        buy_signal_data['close'],
        color="#7CFF82",  # 落ち着いたグリーン
        s=100,
        label='Buy',
        marker='^',
        alpha=0.9,
        edgecolors='#2E7D32',
        linewidths=1.5,
        zorder=5,
        transform=trans_offset
    )

    sell_signal_data = symbol_ohlcv_df.loc[symbol_ohlcv_df['sell_date'].notna(
    )]
    # Y軸方向に+10ピクセルオフセット
    trans_offset_sell = transforms.offset_copy(
        axe.transData, fig=axe.figure, y=10, units='dots')
    axe.scatter(
        sell_signal_data['timestamp'],
        sell_signal_data['close'],
        color="#FF6E6E",  # ソフトなレッド
        s=100,
        label='Sell',
        marker='v',
        alpha=0.9,
        edgecolors='#C62828',
        linewidths=1.5,
        zorder=5,
        transform=trans_offset_sell
    )

    # SARをドットで表示（トレンド転換で色を変更）
    sar_up_mask = ~pd.isna(symbol_ohlcv_df['sar_up'])
    sar_down_mask = ~pd.isna(symbol_ohlcv_df['sar_down'])

    # 上昇トレンド時のSAR（エメラルドグリーン）
    axe.scatter(
        symbol_ohlcv_df.loc[sar_up_mask, 'timestamp'],
        symbol_ohlcv_df.loc[sar_up_mask, 'sar_up'],
        color='#26A69A',
        s=60,
        label='SAR (Bullish)',
        alpha=0.85,
        edgecolors='#1A7A6D',
        linewidths=1.2,
        zorder=4
    )

    # 下降トレンド時のSAR（コーラルレッド）
    axe.scatter(
        symbol_ohlcv_df.loc[sar_down_mask, 'timestamp'],
        symbol_ohlcv_df.loc[sar_down_mask, 'sar_down'],
        color='#EF5350',
        s=60,
        label='SAR (Bearish)',
        alpha=0.85,
        edgecolors='#C62828',
        linewidths=1.2,
        zorder=4
    )

    # SMA50（オレンジゴールド）
    axe.plot(
        symbol_ohlcv_df['timestamp'],
        symbol_ohlcv_df['sma_50'],
        label="SMA 50",
        color='#FFA726',
        linewidth=2.2,
        alpha=0.85,
        linestyle='-',
        zorder=2
    )

    # SMA100（ディープパープル）
    axe.plot(
        symbol_ohlcv_df['timestamp'],
        symbol_ohlcv_df['sma_100'],
        label="SMA 100",
        color='#7E57C2',
        linewidth=2.2,
        alpha=0.85,
        linestyle='-',
        zorder=2
    )

    # 平均価格
    axe.axhline(average_price, color='green', ls='--', lw=1,
                alpha=0.7, label='Average Buy Price')
    axe.text(symbol_ohlcv_df['timestamp'].iloc[0], average_price,
             f" Average Buy : {average_price:.2f}",
             va="bottom", ha="left", fontsize=9)

    axe.grid(True, alpha=0.3, linestyle='--', linewidth=0.8)
    axe.set_title(f"{symbol} Price Chart ({timeframe})",
                  fontsize=18, fontweight='bold', pad=20,
                  color='#2C3E50')
    axe.set_ylabel("Price (USD)", fontsize=13, fontweight='bold')
    axe.set_xlabel("Date", fontsize=13, fontweight='bold')

    # レジェンドをライトテーマでいい感じに
    axe.legend(
        loc='upper left',
        framealpha=0.95,
        fancybox=True,
        shadow=True,
        fontsize=11,
        edgecolor='#CCCCCC',
        facecolor='white'
    )

    # 日付ラベルの重なりを防ぐ
    axe.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    axe.xaxis.set_major_locator(mdates.HourLocator(interval=12))

    axe.tick_params(axis='x', rotation=45)
