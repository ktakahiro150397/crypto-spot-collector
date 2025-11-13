import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
import seaborn as sns
from loguru import logger
from matplotlib import font_manager
from matplotlib import pyplot as plt

from crypto_spot_collector.apps.import_historical_data import HistoricalDataImporter
from crypto_spot_collector.checkers.sar_checker import SARChecker
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.secrets import load_config
from crypto_spot_collector.utils.trade_data import create_update_trade_data

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ログファイル名（日付付き）
log_file = LOG_DIR / f"buy_spot_{datetime.now().strftime('%Y%m%d')}.log"

# loguruのログ設定
# デフォルトのハンドラーを削除
logger.remove()

# 標準出力にログを表示（INFOレベル以上、docker logsで確認可能）
logger.add(
    sink=sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)

# ファイルにログを保存（DEBUGレベル以上、日次ローテーション）
logger.add(
    sink=log_file,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="00:00",  # 毎日0時にローテーション
    retention="30 days",  # 30日間保持
    compression="zip",  # 古いログファイルをzip圧縮
    encoding="utf-8"
)

# --- seaborn 設定 ---
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

# -------


spot_symbol = ["btc", "eth", "xrp", "sol", "link",
               "avax", "hype", "bnb", "doge", "wld", "ltc", "pol",
               "xaut",]

logger.info("Initializing crypto spot collector script")
secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

notificator = discordNotification(secrets["discord"]["discordWebhookUrl"])
importer = HistoricalDataImporter()
logger.info("Discord notification and historical data importer initialized")

bybit_exchange = BybitExchange(
    apiKey=secrets["bybit"]["apiKey"], secret=secrets["bybit"]["secret"]
)
logger.info("Bybit exchange client initialized")


async def main() -> None:
    # 毎時0分に実行
    logger.info("Starting buy spot script")

    logger.info("---- Settings ----")
    logger.info(
        f"Discord Webhook URL: {secrets['discord']['discordWebhookUrl']}")
    logger.info(f"Spot Symbols: {spot_symbol}")
    for setting in secrets["settings"]["timeframes"]:
        logger.info("------------------")
        timeframe = setting["timeframe"]
        amountByUSDT = setting["amountBuyUSDT"]
        consecutivePositiveCount = setting["consecutivePositiveCount"]

        logger.info(f"Timeframe: {timeframe}")
        logger.info(f"AmountByUSDT: {amountByUSDT}")
        logger.info(f"consecutivePositiveCount: {consecutivePositiveCount}")
    logger.info("------------------")

    while True:
        # 次の1時間まで待機処理
        now = datetime.now(timezone.utc)
        logger.info(f"Current time: {now}")
        next_run = (now + timedelta(hours=1)).replace(minute=0,
                                                      second=0, microsecond=0)
        wait_seconds = (next_run - now).total_seconds()
        logger.info(
            f"Waiting for {wait_seconds} seconds until next run at {next_run} UTC")
        await asyncio.sleep(wait_seconds)

        # 時間足の取得・登録
        toDateUtc = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        )
        fromDateUtc = toDateUtc - timedelta(days=7)

        logger.info(f"Fetching OHLCV data from {fromDateUtc} to {toDateUtc}")

        # 過去1日のOHLCVデータを取得して登録
        for symbol in spot_symbol:
            logger.debug(f"Processing {symbol.upper()}/USDT")
            ohlcv = bybit_exchange.fetch_ohlcv(
                symbol=f"{symbol.upper()}/USDT",
                timeframe="1h",
                fromDate=fromDateUtc,
                toDate=toDateUtc,
            )

            # OHLCVデータの登録
            importer.register_data(symbol.upper(), ohlcv)
            logger.debug(f"Registered OHLCV data for {symbol.upper()}")

        for setting in secrets["settings"]["timeframes"]:
            # spot_symbol = setting["spotSymbol"]
            timeframe = setting["timeframe"]
            amountByUSDT = setting["amountBuyUSDT"]
            consecutivePositiveCount = setting["consecutivePositiveCount"]

            timeframe_delta = int(timeframe.replace(
                "m", "").replace("h", "").replace("d", ""))

            # 現時刻が時間足の区切り目であればシグナルチェックを実行
            toJst = toDateUtc.astimezone(timezone(timedelta(hours=9)))
            if toJst.hour % timeframe_delta == 0:
                logger.info(f"Checking signals... timeframe={timeframe}")
                checkEndDate = toDateUtc
                checkStartDate = checkEndDate - timedelta(days=14)

                for symbol in spot_symbol:
                    logger.debug(f"Checking signal for {symbol.upper()}")
                    await check_signal(
                        startDate=checkStartDate,
                        endDate=checkEndDate,
                        symbol=symbol.upper(),
                        timeframe=timeframe,
                        amountByUSDT=amountByUSDT,
                        consecutivePositiveCount=consecutivePositiveCount
                    )
            else:
                logger.info(
                    f"Current hour {toJst.hour} is not a multiple of {timeframe_delta}, skipping signal check"
                )

        # オーダーDBデータの更新
        logger.info("Updating trade data in database...")

        for symbol in spot_symbol:
            closed_trades = bybit_exchange.fetch_close_orders_all(
                symbol=symbol.upper())
            open_trades = bybit_exchange.fetch_open_orders_all(
                symbol=symbol.upper())
            canceled_trades = bybit_exchange.fetch_canceled_orders_all(
                symbol=symbol.upper())
            create_update_trade_data(
                symbol=symbol,
                open_trades=open_trades,
                closed_trades=closed_trades,
                canceled_trades=canceled_trades
            )

        # if toJst.hour == 0:
        #     # 毎日0時に成績通知
        #     await notify_current_portfolio()


async def check_signal(
    startDate: datetime,
    endDate: datetime,
    symbol: str,
    timeframe: str,
    amountByUSDT: float,
    consecutivePositiveCount: int
) -> None:
    """Check for SAR buy/sell signals and send Discord notification if detected."""

    logger.debug(f"Checking signal for {symbol} from {startDate} to {endDate}")

    # Use MarketDataProvider to get DataFrame with indicators
    data_provider = MarketDataProvider()
    df = data_provider.get_dataframe_with_indicators(
        symbol=symbol,
        interval=timeframe,
        from_datetime=startDate,
        to_datetime=endDate,
        sma_windows=[50, 100],
        sar_config={"step": 0.02, "max_step": 0.2}
    )

    logger.debug(f"Retrieved {len(df)} OHLCV records for {symbol}")

    if df.empty:
        logger.warning(f"No data available for {symbol}")
        return

    # Use SARChecker to check for buy signal
    sar_checker = SARChecker(
        consecutive_positive_count=consecutivePositiveCount)
    sar_up_signal = sar_checker.check(df)
    logger.info(f"{symbol}: SAR Up Signal: {sar_up_signal}")

    # デバッグ用：実際の値を表示
    logger.debug(f"{symbol}: Recent SAR Up values (newest first):")
    if sar_up_signal:
        logger.info(f"{symbol}: SAR buy signal detected! Placing order...")
        order_result = None
        try:
            _, order_result = bybit_exchange.create_order_spot(
                amountByUSDT=amountByUSDT, symbol=symbol
            )
            logger.success(f"Successfully created spot order for {symbol}")
        except Exception as e:
            logger.error(f"Error creating spot order for {symbol}: {e}")
            await notificator.send_notification_async(
                message=f"Error creating spot order for {symbol}: {e}",
                files=[]
            )
            return

        # Discord通知
        free_usdt = bybit_exchange.fetch_free_usdt()
        # average_price = bybit_exchange.fetch_average_buy_price_spot(symbol)
        with TradeDataRepository() as repo:
            _, average_price = repo.get_current_position_and_avg_price(
                symbol=symbol
            )

        embed = discordNotification.embed_object_create_helper(
            symbol=symbol,
            price=order_result.price,
            amount=order_result.amount,
            freeUsdt=free_usdt,
            order_value=order_result.order_value,
            order_id=order_result.order_id,
            footer="buy_spot.py | bybit",
            timeframe=timeframe
        )

        # グラフ作成
        plot_buf = [(notification_plot_buff(
            df=df,
            timeframe=timeframe,
            symbol=symbol,
            average_price=average_price,
            limit_price=order_result.price), f"{symbol}_sar.png")]
        await notificator.send_notification_embed_with_file(
            message="",
            embeds=[embed],
            image_buffers=plot_buf
        )
        logger.info(f"Sent Discord notification for {symbol}")

        for i, sar_up in enumerate(df["sar_up"].tail(10)[::-1]):
            logger.debug(f"  {i}: {sar_up}")
    else:
        logger.debug(f"{symbol}: No SAR Up signal detected.")


def notification_plot_buff(df: pd.DataFrame, timeframe: str, symbol: str, average_price: float, limit_price: float) -> BytesIO:
    logger.debug(f"Creating plot for {symbol}")
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

    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"{symbol} Price with Parabolic SAR ({timeframe})")
    ax1.set_ylabel("Price (USD)")
    ax1.legend()

    if average_price > 0:
        ax1.axhline(average_price, color='green', ls='--', lw=1,
                    alpha=0.7, label='Average Buy Price')
        ax1.text(df['timestamp'].iloc[0], average_price,
                 f" Average Buy : {average_price:.2f}",
                 va="bottom", ha="left", fontsize=9)

    if limit_price > 0:
        ax1.axhline(limit_price, color='green', ls="-", lw=1,
                    alpha=0.7, label='Limit Buy Price')
        ax1.text(df['timestamp'].iloc[0], limit_price,
                 f" Limit Buy : {limit_price:.2f}",
                 va="bottom", ha="left", fontsize=9)

    # 日付ラベルの重なりを防ぐ
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=12))

    plt.xticks(rotation=45)
    plt.tight_layout()

    # 画像をメモリ上に保存
    img_buffer1 = BytesIO()
    plt.savefig(img_buffer1, format="png", dpi=150, bbox_inches="tight")
    img_buffer1.seek(0)

    logger.debug(f"Plot for {symbol} created successfully")
    return img_buffer1


if __name__ == "__main__":
    import asyncio

    logger.info("Starting crypto spot collector application")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
