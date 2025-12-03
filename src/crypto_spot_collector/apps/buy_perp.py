import asyncio
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
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.types import PositionSide
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider
from crypto_spot_collector.utils.secrets import load_config

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ログファイル名（日付付き）
log_file = LOG_DIR / f"buy_perp_{datetime.now().strftime('%Y%m%d')}.log"

# loguruのログ設定
# デフォルトのハンドラーを削除
logger.remove()

# 標準出力にログを表示（INFOレベル以上、docker logsで確認可能）
logger.add(
    sink=sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# ファイルにログを保存（DEBUGレベル以上、日次ローテーション）
logger.add(
    sink=log_file,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="INFO",
    rotation="00:00",  # 毎日0時にローテーション
    retention="30 days",  # 30日間保持
    compression="zip",  # 古いログファイルをzip圧縮
    encoding="utf-8",
)

# --- seaborn 設定 ---
# ライトテーマでいい感じのスタイルを設定
sns.set_style("whitegrid")
sns.set_palette("husl")

# カスタムTTFフォントを使用する設定
# 使い方: fontsフォルダにTTFファイルを配置して、ファイル名を指定
# 例: "fonts/Inter-Regular.ttf" or "fonts/Roboto-Regular.ttf"
CUSTOM_FONT_PATH = Path(__file__).parent / "font" / "CourierPrime-Regular.ttf"

if CUSTOM_FONT_PATH and Path(CUSTOM_FONT_PATH).exists():
    # TTFファイルを登録
    font_manager.fontManager.addfont(CUSTOM_FONT_PATH)
    custom_font = font_manager.FontProperties(fname=CUSTOM_FONT_PATH)
    plt.rcParams["font.family"] = custom_font.get_name()
    print(f"カスタムフォントを使用: {custom_font.get_name()}")
else:
    # デフォルトフォント（システムフォント）
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]
    if CUSTOM_FONT_PATH:
        print(
            f"警告: {CUSTOM_FONT_PATH} が見つかりません。デフォルトフォントを使用します。"
        )

plt.rcParams["font.size"] = 11

# ライトテーマの配色
plt.rcParams["figure.facecolor"] = "#FFFFFF"
plt.rcParams["axes.facecolor"] = "#F8F9FA"
plt.rcParams["axes.edgecolor"] = "#CCCCCC"
plt.rcParams["grid.color"] = "#E0E0E0"
plt.rcParams["grid.linestyle"] = "--"
plt.rcParams["grid.linewidth"] = 0.8
plt.rcParams["text.color"] = "#2C3E50"
plt.rcParams["axes.labelcolor"] = "#2C3E50"
plt.rcParams["xtick.color"] = "#2C3E50"
plt.rcParams["ytick.color"] = "#2C3E50"

# -------


# HyperLiquidで取引する永続シンボル
perp_symbols = [
    # "BTC",
    # "ETH",
    "XRP",
    # "SOL",
]

logger.info("Initializing crypto perp collector script")
secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

notificator = discordNotification(
    secrets["discord"]["discordWebhookUrlPerpetual"])
importer = HistoricalDataImporter()
logger.info("Discord notification and historical data importer initialized")

hyperliquid_exchange = HyperLiquidExchange(
    mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
    apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
    privateKey=secrets["hyperliquid"]["privatekey"],
    take_profit_rate=secrets["settings"]["perpetual"]["take_profit_rate"],
    stop_loss_rate=secrets["settings"]["perpetual"]["stop_loss_rate"],
    leverage=secrets["settings"]["perpetual"]["leverage"],
    testnet=False,
)
logger.info("HyperLiquid exchange client initialized")

sar_checker = SARChecker(
    consecutive_count=secrets["settings"]["perpetual"]["consecutivePositiveCount"])

# SAR direction tracking per symbol
# Key: symbol (e.g., "XRP/USDC:USDC"), Value: SAR direction ("long", "short", or None)
sar_direction_tracker: dict[str, str | None] = {}


def check_price_change_signal(
    df: pd.DataFrame, threshold_percent: float
) -> tuple[bool, bool, float, str]:
    """
    最新2つのローソク足から価格変動率を計算し、ロング・ショートシグナルを判断する。

    Args:
        df: OHLCVデータを含むDataFrame
        threshold_percent: 判断基準となる価格変動率（%）

    Returns:
        tuple: (is_long_signal, is_short_signal, price_change_percent, reason)
            - is_long_signal: ロングシグナルの有無
            - is_short_signal: ショートシグナルの有無
            - price_change_percent: 実際の価格変動率（%）
            - reason: 判断理由の説明文
    """
    if len(df) < 2:
        return False, False, 0.0, "Not enough data"

    # 最新2つのローソク足を取得
    prev_candle = df.iloc[-2]
    latest_candle = df.iloc[-1]

    # 1つ前の足のopenと最新のcloseの価格差を計算
    prev_open = prev_candle["open"]
    latest_close = latest_candle["close"]

    # 価格変動率を計算（%）
    price_change_percent = ((latest_close - prev_open) / prev_open) * 100

    # 判断ロジック
    is_long_signal = price_change_percent >= threshold_percent
    is_short_signal = price_change_percent <= -threshold_percent

    # 理由を作成
    if is_long_signal:
        reason = (
            f"Price increased {price_change_percent:.2f}% "
            f"(from {prev_open:.2f} to {latest_close:.2f}), "
            f"threshold: {threshold_percent}%"
        )
    elif is_short_signal:
        reason = (
            f"Price decreased {abs(price_change_percent):.2f}% "
            f"(from {prev_open:.2f} to {latest_close:.2f}), "
            f"threshold: {threshold_percent}%"
        )
    else:
        reason = (
            f"Price change {price_change_percent:.2f}% "
            f"is within threshold ±{threshold_percent}%"
        )

    logger.debug(
        f"Price change analysis: {price_change_percent:.2f}% "
        f"(prev_open: {prev_open}, latest_close: {latest_close}), "
        f"Long: {is_long_signal}, Short: {is_short_signal}"
    )

    return is_long_signal, is_short_signal, price_change_percent, reason


def should_long(df: pd.DataFrame, threshold_percent: float) -> tuple[bool, str]:
    """
    ロング（買い）シグナルを判断する関数。
    SARシグナルまたは価格変動率シグナルのいずれかを満たす場合にロング。

    Args:
        df: OHLCVデータを含むDataFrame（インジケーター付き）
        threshold_percent: 価格変動率の判断基準（%）

    Returns:
        tuple: (is_long_signal, reason)
            - is_long_signal: ロングシグナルの有無
            - reason: 判断理由
    """
    # SARシグナルチェック
    is_long_sar = sar_checker.check_long(df)
    logger.info(f"should_long: SAR long signal: {is_long_sar}")

    # 価格変動率シグナルチェック
    is_long_price, _, price_change_pct, price_reason = check_price_change_signal(
        df, threshold_percent
    )
    logger.info(f"should_long: Price change long signal: {is_long_price}")

    # いずれかのシグナルが発生した場合にロング
    is_long = is_long_sar or is_long_price

    # 理由を作成
    reasons = []
    if is_long_sar:
        reasons.append("SAR bullish signal")
    if is_long_price:
        reasons.append(price_reason)

    reason = " | ".join(reasons) if reasons else "No long signal"

    return is_long, reason


def should_short(df: pd.DataFrame, threshold_percent: float) -> tuple[bool, str]:
    """
    ショート（売り）シグナルを判断する関数。
    SARシグナルまたは価格変動率シグナルのいずれかを満たす場合にショート。

    Args:
        df: OHLCVデータを含むDataFrame（インジケーター付き）
        threshold_percent: 価格変動率の判断基準（%）

    Returns:
        tuple: (is_short_signal, reason)
            - is_short_signal: ショートシグナルの有無
            - reason: 判断理由
    """
    # SARシグナルチェック
    is_short_sar = sar_checker.check_short(df)
    logger.info(f"should_short: SAR short signal: {is_short_sar}")

    # 価格変動率シグナルチェック
    _, is_short_price, price_change_pct, price_reason = check_price_change_signal(
        df, threshold_percent
    )
    logger.info(f"should_short: Price change short signal: {is_short_price}")

    # いずれかのシグナルが発生した場合にショート
    is_short = is_short_sar or is_short_price

    # 理由を作成
    reasons = []
    if is_short_sar:
        reasons.append("SAR bearish signal")
    if is_short_price:
        reasons.append(price_reason)

    reason = " | ".join(reasons) if reasons else "No short signal"

    return is_short, reason


async def main() -> None:
    """メインループ: 毎分0秒に実行"""
    logger.info("Starting buy perp script")

    timeframe_perp = secrets["settings"]["perpetual"].get("timeframe", "5m")

    logger.info("---- Settings ----")
    logger.info(
        f"Discord Webhook URL: {secrets['discord']['discordWebhookUrlPerpetual']}")
    logger.info(f"Perp Symbols: {perp_symbols}")
    logger.info(f"Timeframe: {timeframe_perp}")
    logger.info(
        f"Take Profit Rate: {secrets['settings']['perpetual']['take_profit_rate']}"
    )
    logger.info(
        f"Stop Loss Rate: {secrets['settings']['perpetual']['stop_loss_rate']}")
    logger.info(f"Leverage: {secrets['settings']['perpetual']['leverage']}")
    logger.info("------------------")

    # 注文金額（USDC）
    amount_by_usdc = secrets["settings"]["perpetual"].get("amountByUSDC", 10.0)

    while True:
        # 次の実行時刻まで待機処理
        now = datetime.now(timezone.utc)
        logger.info(f"Current time: {now}")

        run_minute = int(timeframe_perp.replace("m", ""))

        # 次の実行時刻を計算（run_minuteの倍数の分に実行）
        current_minute = now.minute
        current_second = now.second

        # 次の実行分を計算（run_minuteの倍数）
        next_minute = ((current_minute // run_minute) + 1) * run_minute

        if next_minute >= 60:
            # 次の時間に繰り越し
            next_run = (now + timedelta(hours=1)).replace(minute=0,
                                                          second=0, microsecond=0)
        else:
            # 同じ時間内
            next_run = now.replace(minute=next_minute, second=0, microsecond=0)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(
            f"Waiting for {wait_seconds:.1f} seconds until next run at {next_run} UTC "
            f"(run every {run_minute} minutes: 0, {run_minute}, {run_minute*2}, ...)"
        )
        await asyncio.sleep(wait_seconds)

        # 時間足の取得・登録
        toDateUtc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        fromDateUtc = toDateUtc - timedelta(days=1)  # 過去2分のデータを取得

        logger.info(f"Fetching OHLCV data from {fromDateUtc} to {toDateUtc}")

        # 各シンボルについて処理
        for symbol in perp_symbols:
            try:
                logger.debug(f"Processing {symbol}/USDC:USDC")

                # 過去1時間のOHLCVデータを取得
                ohlcv = await hyperliquid_exchange.fetch_ohlcv_async(
                    symbol=f"{symbol}/USDC:USDC",
                    timeframe=timeframe_perp,
                    fromDate=fromDateUtc,
                    toDate=toDateUtc,
                )

                logger.debug(
                    f"Fetched {len(ohlcv)} OHLCV records for {symbol}")
                if ohlcv:
                    logger.debug(
                        f"First OHLCV record timestamp: {ohlcv[0][0]} ({datetime.fromtimestamp(ohlcv[0][0]/1000, tz=timezone.utc)})")
                    logger.debug(
                        f"Last OHLCV record timestamp: {ohlcv[-1][0]} ({datetime.fromtimestamp(ohlcv[-1][0]/1000, tz=timezone.utc)})")

                # OHLCVデータの登録
                importer.register_data(f"{symbol}/USDC:USDC", ohlcv)
                logger.debug(f"Registered OHLCV data for {symbol.upper()}")

                # シグナルチェック
                await check_signal(
                    startDate=fromDateUtc,
                    endDate=toDateUtc,
                    symbol=f"{symbol}/USDC:USDC",
                    timeframe=timeframe_perp,
                    amountByUSDC=amount_by_usdc,
                )
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue


async def check_signal(
    startDate: datetime,
    endDate: datetime,
    symbol: str,
    timeframe: str,
    amountByUSDC: float,
) -> None:
    """シグナルをチェックし、ロング/ショートのオーダーを発注する。"""

    logger.debug(f"Checking signal for {symbol} from {startDate} to {endDate}")

    # Use MarketDataProvider to get DataFrame with indicators
    data_provider = MarketDataProvider()
    df = data_provider.get_dataframe_with_indicators(
        symbol=symbol,
        interval=timeframe,
        from_datetime=startDate,
        to_datetime=endDate,
        sma_windows=[20, 50],
        sar_config={"step": 0.02, "max_step": 0.2},
    )

    logger.debug(f"Retrieved {len(df)} OHLCV records for {symbol}")

    if df.empty:
        logger.warning(f"No data available for {symbol}")
        return

    # Check for SAR direction switch (to close existing positions)
    previous_sar_direction = sar_direction_tracker.get(symbol)
    sar_switched, current_sar_direction = sar_checker.check_sar_direction_switch(
        df, previous_sar_direction
    )

    # Update the tracker with current direction
    sar_direction_tracker[symbol] = current_sar_direction

    logger.info(
        f"{symbol}: SAR direction - Previous: {previous_sar_direction}, "
        f"Current: {current_sar_direction}, Switched: {sar_switched}"
    )

    # If SAR direction switched, close all positions
    if sar_switched:
        logger.info(
            f"{symbol}: SAR direction switched from {previous_sar_direction} "
            f"to {current_sar_direction}. Closing all positions."
        )
        closed_positions = await hyperliquid_exchange.close_all_positions_perp_async(
            side=PositionSide.ALL
        )

        # Send Discord notification for closed positions
        if closed_positions:
            await send_close_position_notification(
                symbol=symbol,
                closed_positions=closed_positions,
                reason=f"SAR direction switch: {previous_sar_direction} → {current_sar_direction}",
                timeframe=timeframe,
            )

    # Check for new entry signals
    threshold_percent = secrets["settings"]["perpetual"].get(
        "price_change_threshold_percent", 0.5
    )

    long_signal, long_reason = should_long(df, threshold_percent)
    short_signal, short_reason = should_short(df, threshold_percent)

    logger.info(
        f"{symbol}: Long Signal: {long_signal} ({long_reason}), "
        f"Short Signal: {short_signal} ({short_reason})"
    )

    if long_signal:
        await execute_long_order(
            symbol=symbol,
            timeframe=timeframe,
            df=df,
            amountByUSDC=amountByUSDC,
            reason=long_reason,
        )
    elif short_signal:
        await execute_short_order(
            symbol=symbol,
            timeframe=timeframe,
            df=df,
            amountByUSDC=amountByUSDC,
            reason=short_reason,
        )
    else:
        logger.debug(f"{symbol}: No signal detected.")


async def execute_long_order(
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    amountByUSDC: float,
    reason: str = "",
) -> None:
    """ロングオーダーを発注する。"""
    logger.info(f"{symbol}: Long signal detected! Placing long order...")
    logger.info(f"{symbol}: Reason: {reason}")

    try:
        # 現在価格を取得
        ticker = await hyperliquid_exchange.fetch_price_async(f"{symbol}")
        current_price = ticker["last"]

        # 注文数量を計算
        amount = amountByUSDC / current_price

        # ロングオーダー発注
        order_result = await hyperliquid_exchange.create_order_perp_long_async(
            symbol=f"{symbol}",
            amount=amount,
            price=current_price,
        )
        logger.success(f"Successfully created long order for {symbol}")

        # Discord通知
        free_usdc = await hyperliquid_exchange.fetch_free_usdt_async()

        embed = embed_object_create_helper_perp(
            symbol=symbol,
            price=current_price,
            amount=amount,
            freeUsdc=free_usdc,
            order_value=amountByUSDC,
            order_id=order_result.get("id", "N/A"),
            position_type="LONG",
            footer="buy_perp.py | hyperliquid",
            timeframe=timeframe,
            reason=reason,
        )

        # グラフ作成
        plot_buf = [
            (
                notification_plot_buff(
                    df=df,
                    timeframe=timeframe,
                    symbol=symbol,
                    entry_price=current_price,
                ),
                f"{symbol}_perp.png",
            )
        ]
        await notificator.send_notification_embed_with_file(
            message="", embeds=[embed], image_buffers=plot_buf
        )
        logger.info(f"Sent Discord notification for {symbol} long order")

    except Exception as e:
        logger.error(f"Error creating long order for {symbol}: {e}")
        await notificator.send_notification_async(
            message=f"Error creating long order for {symbol}: {e}", files=[]
        )


async def execute_short_order(
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    amountByUSDC: float,
    reason: str = "",
) -> None:
    """ショートオーダーを発注する。"""
    logger.info(f"{symbol}: Short signal detected! Placing short order...")
    logger.info(f"{symbol}: Reason: {reason}")

    try:
        # 現在価格を取得
        ticker = await hyperliquid_exchange.fetch_price_async(f"{symbol}")
        current_price = ticker["last"]

        # 注文数量を計算
        amount = amountByUSDC / current_price

        # ショートオーダー発注
        order_result = await hyperliquid_exchange.create_order_perp_short_async(
            symbol=f"{symbol}",
            amount=amount,
            price=current_price,
        )
        logger.success(f"Successfully created short order for {symbol}")

        # Discord通知
        free_usdc = await hyperliquid_exchange.fetch_free_usdt_async()

        embed = embed_object_create_helper_perp(
            symbol=symbol,
            price=current_price,
            amount=amount,
            freeUsdc=free_usdc,
            order_value=amountByUSDC,
            order_id=order_result.get("id", "N/A"),
            position_type="SHORT",
            footer="buy_perp.py | hyperliquid",
            timeframe=timeframe,
            reason=reason,
        )

        # グラフ作成
        plot_buf = [
            (
                notification_plot_buff(
                    df=df,
                    timeframe=timeframe,
                    symbol=symbol,
                    entry_price=current_price,
                ),
                f"{symbol}_perp.png",
            )
        ]
        await notificator.send_notification_embed_with_file(
            message="", embeds=[embed], image_buffers=plot_buf
        )
        logger.info(f"Sent Discord notification for {symbol} short order")

    except Exception as e:
        logger.error(f"Error creating short order for {symbol}: {e}")
        await notificator.send_notification_async(
            message=f"Error creating short order for {symbol}: {e}", files=[]
        )


def embed_object_create_helper_perp(
    symbol: str,
    price: float,
    amount: float,
    freeUsdc: float,
    order_value: float,
    order_id: str,
    position_type: str,
    timeframe: str,
    footer: str,
    reason: str = "",
) -> dict:
    """Create a Discord embed object for perp notifications."""
    if position_type == "LONG":
        title = f":chart_with_upwards_trend: ({timeframe}) {symbol} ロングシグナルを検知しました！"
        color = 3066993  # 緑色
    else:
        title = f":chart_with_downwards_trend: ({timeframe}) {symbol} ショートシグナルを検知しました！"
        color = 15158332  # 赤色

    fields = []

    # 理由フィールドを最初に追加（存在する場合）
    if reason:
        fields.append({
            "name": "🔍 シグナル理由",
            "value": f"`{reason}`",
            "inline": False,
        })

    # その他のフィールドを追加
    fields.extend([
        {
            "name": "ポジションタイプ",
            "value": f"`{position_type}`",
            "inline": True,
        },
        {
            "name": "エントリー価格",
            "value": f"`{price}`",
            "inline": True,
        },
        {
            "name": f"{symbol} 数量",
            "value": f"`{amount}`",
            "inline": True,
        },
        {
            "name": "注文合計金額",
            "value": f"`{order_value}`",
            "inline": True,
        },
        {
            "name": "残りUSDC",
            "value": f"`{freeUsdc}`",
            "inline": True,
        },
        {
            "name": "オーダーID",
            "value": f"`{order_id}`",
            "inline": True,
        },
    ])

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"{footer}",
        },
    }
    return embed


async def send_close_position_notification(
    symbol: str,
    closed_positions: list[dict],
    reason: str,
    timeframe: str,
) -> None:
    """ポジションクローズ時のDiscord通知を送信する。"""
    try:
        logger.info(f"Sending close position notification for {symbol}")

        # 残高を取得
        free_usdc = await hyperliquid_exchange.fetch_free_usdt_async()

        # クローズされたポジションの情報を集約
        total_contracts = 0.0
        position_details = []

        for pos in closed_positions:
            contracts = pos.get("amount", 0.0)
            total_contracts += contracts

            # ポジション詳細を追加
            side = pos.get("side", "N/A")
            price = pos.get("price", 0.0)
            order_id = pos.get("id", "N/A")

            position_details.append({
                "side": side,
                "contracts": contracts,
                "price": price,
                "order_id": order_id,
            })

        # Embed作成
        embed = {
            "title": f":octagonal_sign: ({timeframe}) {symbol} ポジションをクローズしました",
            "color": 16776960,  # 黄色
            "fields": [
                {
                    "name": "クローズ理由",
                    "value": f"`{reason}`",
                    "inline": False,
                },
                {
                    "name": "クローズしたポジション数",
                    "value": f"`{len(closed_positions)}`",
                    "inline": True,
                },
                {
                    "name": "残りUSDC",
                    "value": f"`{free_usdc}`",
                    "inline": True,
                },
            ],
            "footer": {
                "text": "buy_perp.py | hyperliquid",
            },
        }

        # 各ポジションの詳細を追加
        for i, detail in enumerate(position_details, 1):
            embed["fields"].append({
                "name": f"Position #{i} - {detail['side'].upper()}",
                "value": (
                    f"数量: `{detail['contracts']}`\n"
                    f"価格: `{detail['price']}`\n"
                    f"Order ID: `{detail['order_id']}`"
                ),
                "inline": True,
            })

        await notificator.send_notification_embed_with_file(
            message="", embeds=[embed], image_buffers=[]
        )
        logger.info(f"Close position notification sent for {symbol}")

    except Exception as e:
        logger.error(
            f"Error sending close position notification for {symbol}: {e}")


def notification_plot_buff(
    df: pd.DataFrame,
    timeframe: str,
    symbol: str,
    entry_price: float,
) -> BytesIO:
    """グラフを作成し、BytesIOとして返す。"""
    logger.debug(f"Creating plot for {symbol}")

    # 最新の60データポイントのみ使用
    df = df.tail(60).copy()

    fig, ax1 = plt.subplots(1, 1, figsize=(12, 8))

    # 価格チャート
    ax1.plot(
        df["timestamp"], df["close"], label="Close Price", color="blue", linewidth=2
    )

    # SARをドットで表示（トレンド転換で色を変更）
    if "sar_up" in df.columns:
        sar_up_mask = ~pd.isna(df["sar_up"])
        ax1.scatter(
            df.loc[sar_up_mask, "timestamp"],
            df.loc[sar_up_mask, "sar_up"],
            color="green",
            s=30,
            label="SAR (Bullish)",
            alpha=0.8,
        )

    if "sar_down" in df.columns:
        sar_down_mask = ~pd.isna(df["sar_down"])
        ax1.scatter(
            df.loc[sar_down_mask, "timestamp"],
            df.loc[sar_down_mask, "sar_down"],
            color="red",
            s=30,
            label="SAR (Bearish)",
            alpha=0.8,
        )

    # SMA20（オレンジゴールド）
    if "sma_20" in df.columns:
        ax1.plot(
            df["timestamp"],
            df["sma_20"],
            label="SMA 20",
            color="#FFA726",
            linewidth=2.2,
            alpha=0.85,
            linestyle="-",
            zorder=2,
        )

    # SMA50
    if "sma_50" in df.columns:
        ax1.plot(
            df["timestamp"],
            df["sma_50"],
            label="SMA 50",
            color="#42A5F5",
            linewidth=2.2,
            alpha=0.85,
            linestyle="-",
            zorder=2,
        )

    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"{symbol} Price with Parabolic SAR ({timeframe})")
    ax1.set_ylabel("Price (USD)")
    ax1.legend()

    if entry_price > 0:
        ax1.axhline(
            entry_price,
            color="purple",
            ls="-",
            lw=2,
            alpha=0.7,
            label="Entry Price",
        )
        ax1.text(
            df["timestamp"].iloc[0],
            entry_price,
            f" Entry : {entry_price:.2f}",
            va="bottom",
            ha="left",
            fontsize=9,
        )

    # 日付ラベルの重なりを防ぐ
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax1.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))

    plt.xticks(rotation=45)
    plt.tight_layout()

    # 画像をメモリ上に保存
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format="png", dpi=150, bbox_inches="tight")
    img_buffer.seek(0)
    plt.close()

    logger.debug(f"Plot for {symbol} created successfully")
    return img_buffer


if __name__ == "__main__":
    logger.info("Starting crypto perp collector application")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
