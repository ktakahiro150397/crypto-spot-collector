import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import pandas as pd
import seaborn as sns
from ccxt.base.types import Position
from loguru import logger
from matplotlib import font_manager
from matplotlib import pyplot as plt

from crypto_spot_collector.apps.import_historical_data import HistoricalDataImporter
from crypto_spot_collector.checkers.sar_checker import SARChecker
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.trailingstop.trailingstop_manager import (
    TrailingStopManagerHyperLiquid,
    normalized_pnl_percentage,
)
from crypto_spot_collector.exchange.types import PositionSide
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider
from crypto_spot_collector.trading.config import SignalMode, TradingConfig
from crypto_spot_collector.trading.execution import PositionExecutionCoordinator
from crypto_spot_collector.trading.order_state import (
    IdempotentOrderExecutor,
    OrderStatus,
    SQLiteOrderIntentStore,
    create_intent,
)
from crypto_spot_collector.trading.protection import (
    ProtectionError,
    ProtectionReconciler,
)
from crypto_spot_collector.trading.runtime import RuntimeSupervisor
from crypto_spot_collector.trading.strategy import (
    CandleGate,
    SQLiteSarStateStore,
    latest_closed_identity,
)
from crypto_spot_collector.utils.close_position_notification import (
    close_position_notification_message,
)
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
    level="INFO",
    colorize=True,
)

# ファイルにログを保存（DEBUGレベル以上、日次ローテーション）
logger.add(
    sink=log_file,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
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
    logger.info(f"カスタムフォントを使用: {custom_font.get_name()}")
else:
    # デフォルトフォント（システムフォント）
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]
    if CUSTOM_FONT_PATH:
        logger.warning(
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
    "BTC/USDC:USDC",
    "ETH/USDC:USDC",
    "XRP/USDC:USDC",
    "SOL/USDC:USDC",
    "HYPE/USDC:USDC",
    "ZEC/USDC:USDC",
    "FARTCOIN/USDC:USDC",
    "LINK/USDC:USDC",
    "AVAX/USDC:USDC",
    "ADA/USDC:USDC",
    "LTC/USDC:USDC",
]

logger.info("Initializing crypto perp collector script")
secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

# Validate every safety-critical setting before constructing clients or opening
# any network connection. Mainnet confirmation must come from the environment;
# it is deliberately not stored in settings.json.
trading_config = TradingConfig.from_mapping(
    secrets["settings"],
    symbols=perp_symbols,
    mainnet_confirmation=os.getenv("HYPERLIQUID_MAINNET_CONFIRMATION", ""),
)

notificator = discordNotification(secrets["discord"]["discordWebhookUrlPerpetual"])
importer = HistoricalDataImporter()
logger.info("Discord notification and historical data importer initialized")

hyperliquid_exchange = HyperLiquidExchange(
    mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
    apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
    privateKey=secrets["hyperliquid"]["privatekey"],
    trading_config=trading_config,
)
logger.info("HyperLiquid exchange client initialized")

sar_checker = SARChecker(
    consecutive_count=secrets["settings"]["perpetual"]["consecutivePositiveCount"]
)

trailing_manager = TrailingStopManagerHyperLiquid()
background_tasks: set[asyncio.Task] = set()
candle_gate = CandleGate()
runtime_state_path = Path(__file__).parent / "state" / "order_intents.sqlite"
order_intent_store = SQLiteOrderIntentStore(runtime_state_path)
sar_state_store = SQLiteSarStateStore(runtime_state_path)
order_executor = IdempotentOrderExecutor(hyperliquid_exchange, order_intent_store)
protection_reconciler = ProtectionReconciler(
    hyperliquid_exchange,
    take_profit_roe=trading_config.take_profit_roe,
    stop_loss_roe=trading_config.stop_loss_roe,
    leverage=trading_config.leverage,
)
execution_coordinator = PositionExecutionCoordinator(
    hyperliquid_exchange,
    order_executor,
    protection_reconciler,
    expected_leverage=trading_config.leverage,
    expected_margin_mode=trading_config.margin_mode,
)


async def handle_ws_reconnect() -> None:
    """Reconcile the missed interval before normal callbacks resume."""
    await protection_reconciler.reconcile_all(perp_symbols)
    await notificator.send_notification_async(
        message="Hyperliquid WebSocket reconnected; exchange snapshot reconciled.",
        files=[],
    )


hyperliquid_exchange.ws_client.set_reconnect_callback(handle_ws_reconnect)

last_close_position_notification_time = datetime.now(timezone.utc)


async def initialize_trailing_manager() -> None:
    """スクリプト起動時に既存のポジションとTP/SL注文を取得してTrailingManagerを初期化する"""
    logger.info("Initializing TrailingManager with existing positions...")

    try:
        trailing_manager.clear_positions()

        # Adopt the exchange snapshot and prove every live position has a
        # verified TP/SL pair before the strategy loops are allowed to start.
        await protection_reconciler.reconcile_all(perp_symbols)

        # 全シンボルの既存ポジションを取得
        all_positions = await hyperliquid_exchange.exchange_public.fetch_positions()

        initialized_count = 0
        for pos in all_positions:
            contracts = pos.get("contracts", 0)
            if not contracts or float(contracts) == 0:
                continue

            symbol = pos.get("symbol")
            if symbol not in perp_symbols:
                logger.debug(f"Skipping {symbol} (not in monitoring list)")
                continue

            position_side_str = pos.get("side")  # 'long' or 'short'
            entry_price = float(pos.get("entryPrice", 0))

            if position_side_str == "long":
                position_side = PositionSide.LONG
            elif position_side_str == "short":
                position_side = PositionSide.SHORT
            else:
                logger.warning(
                    f"Unknown position side '{position_side_str}' for {symbol}"
                )
                continue

            # TP/SL注文情報を取得
            try:
                tp_sl_info = await hyperliquid_exchange.fetch_tp_sl_info(symbol=symbol)

                if tp_sl_info is None:
                    logger.warning(
                        f"No TP/SL orders found for {symbol}. "
                        "Position will not be managed by TrailingManager."
                    )
                    continue

                # 既存ポジションのトレーリング状態を判定
                # LONG: SL >= entry → trailing_activated = True
                # SHORT: SL <= entry → trailing_activated = True
                current_sl_price = tp_sl_info.stop_loss_trigger_price
                if position_side == PositionSide.LONG:
                    trailing_activated = current_sl_price >= entry_price
                else:  # SHORT
                    trailing_activated = current_sl_price <= entry_price

                # TrailingManagerにポジションを登録
                trailing_manager.add_or_update_position(
                    symbol=symbol,
                    side=position_side,
                    entry_price=entry_price,
                    contracts=float(contracts),
                    stoploss_order_id=tp_sl_info.stop_loss_order_id,
                    initial_stoploss_price=tp_sl_info.stop_loss_trigger_price,
                    trailing_activated=trailing_activated,
                )

                initialized_count += 1
                logger.info(
                    f"Initialized TrailingManager for {symbol}: "
                    f"side={position_side.value}, entry={entry_price:.4f}, "
                    f"initial_sl={tp_sl_info.stop_loss_trigger_price:.4f}, "
                    f"trailing_activated={trailing_activated}"
                )

            except Exception as e:
                logger.error(f"Failed to initialize TrailingManager for {symbol}: {e}")
                continue

        logger.info(
            f"TrailingManager initialization complete. "
            f"Initialized {initialized_count} position(s)."
        )

    except Exception as e:
        logger.error(f"Error during TrailingManager initialization: {e}")
        raise ProtectionError(
            "startup protection reconciliation failed; trading is inhibited"
        ) from e


async def sync_trailing_position(positions: list[Position]) -> None:
    try:
        logger.debug(
            "Synchronizing TrailingManager positions with current Hyperliquid order state..."
        )

        synced_count = 0
        active_symbols: set[str] = set()
        for pos in positions:
            contracts = pos.get("contracts", 0)
            if not contracts or float(contracts) == 0:
                continue

            symbol = pos.get("symbol")
            if symbol not in perp_symbols:
                continue

            position_side_str = pos.get("side")  # 'long' or 'short'
            entry_price = float(pos.get("entryPrice", 0))

            if position_side_str == "long":
                position_side = PositionSide.LONG
            elif position_side_str == "short":
                position_side = PositionSide.SHORT
            else:
                continue

            # TP/SL注文情報を取得
            tp_sl_info = await hyperliquid_exchange.fetch_tp_sl_info(symbol=symbol)
            if tp_sl_info is None:
                logger.warning(
                    f"No TP/SL orders found for {symbol}, remove Trailing Stop Position."
                )
                trailing_manager.remove_position(symbol=symbol)
                continue

            # 既存ポジションのトレーリング状態を判定
            # LONG: SL >= entry → trailing_activated = True
            # SHORT: SL <= entry → trailing_activated = True
            current_sl_price = tp_sl_info.stop_loss_trigger_price
            if position_side == PositionSide.LONG:
                new_trailing_activated = current_sl_price >= entry_price
            else:  # SHORT
                new_trailing_activated = current_sl_price <= entry_price

            # TrailingManagerのポジションを更新
            trailing_manager.add_or_update_position(
                symbol=symbol,
                side=position_side,
                entry_price=entry_price,
                contracts=float(contracts),
                stoploss_order_id=tp_sl_info.stop_loss_order_id,
                initial_stoploss_price=tp_sl_info.stop_loss_trigger_price,
                trailing_activated=new_trailing_activated,
            )
            active_symbols.add(symbol)
            synced_count += 1

        trailing_manager.remove_missing(active_symbols)
        logger.debug(f"Sync complete. Updated {synced_count} position(s).")

    except Exception as e:
        logger.error(f"Error during TrailingManager synchronization: {e}")


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


async def trailing_stop_loop() -> None:
    """
    トレーリングストップ管理ループ: 設定された間隔（デフォルト15分）ごとに実行。
    毎時0, 15, 30, 45分などに実行される。
    """
    interval_minutes = trading_config.trailing_interval_minutes
    activation_pnl_percent = trading_config.trailing_activation_roe

    logger.info(
        f"Starting trailing stop loop. "
        f"Interval: {interval_minutes} minutes, "
        f"Activation PnL: {activation_pnl_percent}%"
    )

    while True:
        try:
            # 次の実行時刻まで待機（interval_minutesの倍数の分に実行）
            now = datetime.now(timezone.utc)
            current_minute = now.minute

            # 次の実行分を計算（interval_minutesの倍数: 0, 15, 30, 45など）
            next_minute = ((current_minute // interval_minutes) + 1) * interval_minutes

            if next_minute >= 60:
                # 次の時間に繰り越し
                next_run = (now + timedelta(hours=1)).replace(
                    minute=0, second=0, microsecond=0
                )
            else:
                # 同じ時間内
                next_run = now.replace(minute=next_minute, second=0, microsecond=0)

            wait_seconds = (next_run - now).total_seconds()
            logger.debug(
                f"[Trailing Stop] Waiting {wait_seconds:.1f}s until {next_run} UTC"
            )
            await asyncio.sleep(wait_seconds)

            # 全ポジションを取得してトレーリングストップをチェック
            logger.info(
                "[Trailing Stop] Checking positions for trailing stop updates..."
            )

            positions = await hyperliquid_exchange.exchange_public.fetch_positions()
            await sync_trailing_position(positions=positions)

            for pos in positions:
                contracts = pos.get("contracts", 0)
                if not contracts or float(contracts) == 0:
                    continue

                symbol = pos.get("symbol")
                if symbol not in perp_symbols:
                    continue

                try:
                    pnl_percent = normalized_pnl_percentage(
                        pos.get("percentage", 0),
                        pos.get("unrealizedPnl", 0),
                    )
                except (TypeError, ValueError) as exc:
                    logger.error(
                        f"[Trailing Stop] {symbol}: invalid PnL snapshot; "
                        f"skipping activation: {exc}"
                    )
                    continue

                # TrailingManagerにポジションが登録されているか確認
                trailing_position = trailing_manager.get_position(symbol=symbol)
                if trailing_position is None:
                    logger.debug(
                        f"[Trailing Stop] {symbol}: Not in TrailingManager, skipping"
                    )
                    continue

                # PnLチェック
                if pnl_percent < activation_pnl_percent:
                    logger.debug(
                        f"[Trailing Stop] {symbol}: PnL {pnl_percent:.2f}% < "
                        f"{activation_pnl_percent}%, skipping"
                    )
                    continue

                # PnL条件を満たした
                logger.info(
                    f"[Trailing Stop] {symbol}: PnL {pnl_percent:.2f}% >= "
                    f"{activation_pnl_percent}%"
                )

                # 現在価格を取得
                ticker = await hyperliquid_exchange.fetch_price_async(symbol)
                current_price = float(ticker["last"])

                # トレーリングが未有効化の場合、有効化する
                if not trailing_position.trailing_activated:
                    activated = trailing_manager.activate_trailing(
                        symbol=symbol,
                        current_price=current_price,
                    )
                    if activated:
                        # ストップロス注文を更新（エントリー価格に設定）
                        await update_stoploss_order(
                            symbol=symbol,
                            position=trailing_position,
                        )
                        trailing_notification_message = f"{symbol} : 損失なしのトレーリングストップが有効です！やったね！"
                        await notificator.send_notification_async(
                            message=trailing_notification_message, files=[]
                        )
                else:
                    # トレーリング有効化済み：通常のトレーリング更新
                    await check_trailing_stop(
                        symbol=symbol,
                        current_price=current_price,
                    )

        except Exception as e:
            logger.error(f"Error in trailing stop loop: {e}")
            # エラー発生時も継続
            await asyncio.sleep(60)


async def update_stoploss_order(
    symbol: str,
    position: Any,
) -> None:
    """ストップロス注文を更新する（トレーリング有効化時）"""
    try:
        await protection_reconciler.reconcile_symbol(
            symbol=symbol,
            trailing_stop=position.current_stoploss_price,
        )
        logger.info(
            f"[Trailing Stop] Activated and updated stoploss for {symbol} "
            f"to entry price {position.current_stoploss_price:.4f}"
        )
    except Exception as e:
        logger.error(f"Error updating stoploss order for {symbol}: {e}")
        raise


def handle_userFills(fill_data: dict[str, Any]) -> None:
    global last_close_position_notification_time
    try:
        fills = fill_data.get("fills", [])

        # クローズポジションのみを抽出
        close_fills = [
            fill
            for fill in fills
            if str(fill.get("dir", "")).lower().find("close") != -1
        ]

        if not close_fills:
            return

        # 最新のクローズポジションを取得（タイムスタンプでソート）
        latest_fill = max(close_fills, key=lambda x: x.get("time", 0))

        time = latest_fill.get("time", 0)
        if time > 0:
            import datetime

            dt_object = datetime.datetime.fromtimestamp(time / 1000, tz=timezone.utc)

            # 既に通知済みの場合はスキップ
            if last_close_position_notification_time >= dt_object:
                logger.debug(
                    f"Skipping notification for {dt_object} (already notified)"
                )
                return

            # 通知処理
            coin = latest_fill.get("coin", "")
            symbol = f"{coin}/USDC:USDC"
            pnl = float(latest_fill.get("closedPnl", 0))
            fee = float(latest_fill.get("fee", 0))
            feeToken = latest_fill.get("feeToken", "")
            dir = str(latest_fill.get("dir", ""))

            notification_message = close_position_notification_message(
                close_date_utc=dt_object,
                symbol=symbol,
                direction=dir,
                pnl=pnl,
                fee=fee,
                feeToken=feeToken,
            )

            task = asyncio.create_task(
                notificator.send_notification_async(
                    message=notification_message, files=[]
                )
            )
            background_tasks.add(task)

            task.add_done_callback(background_tasks.discard)
            last_close_position_notification_time = dt_object
    except Exception as e:
        logger.error(f"Error in handle_userFills: {e}")


async def close_position_notification_loop() -> None:
    try:
        await hyperliquid_exchange.subscribe_userFills_ws(
            callback=handle_userFills,
        )
        logger.info("Subscriptions for userFills set up.")

        # Wait indefinitely - listener is started in main()
        stop_event = asyncio.Event()
        await stop_event.wait()
    except Exception as e:
        logger.error(f"Error in userFills loop: {e}")
    finally:
        logger.error("userFills loop terminated.")


async def heartbeat_loop(interval_seconds: float = 900.0) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        metrics = hyperliquid_exchange.rest.metrics
        retries = sum(item.retries for item in metrics.values())
        failures = sum(item.failures for item in metrics.values())
        await notificator.send_notification_async(
            message=(
                f"Hyperliquid bot heartbeat: network={trading_config.network.value}, "
                f"ws_reconnects={hyperliquid_exchange.ws_client.reconnect_count}, "
                f"rest_retries={retries}, rest_failures={failures}"
            ),
            files=[],
        )


async def signal_check_loop() -> None:
    """シグナルチェックループ: timeframeごとに実行"""
    logger.info("Starting signal check loop")

    timeframe_perp = secrets["settings"]["perpetual"].get("timeframe", "5m")

    logger.info("---- Settings ----")
    logger.info("Discord notification: configured")
    logger.info(f"Perp Symbols: {perp_symbols}")
    logger.info(f"Timeframe: {timeframe_perp}")
    logger.info(
        f"Take Profit Rate: {secrets['settings']['perpetual']['take_profit_rate']}"
    )
    logger.info(f"Stop Loss Rate: {secrets['settings']['perpetual']['stop_loss_rate']}")
    logger.info(f"Leverage: {secrets['settings']['perpetual']['leverage']}")
    logger.info("------------------")

    # 注文金額（USDC）
    amount_by_usdc = secrets["settings"]["perpetual"].get("amountByUSDC", 10.0)

    while True:
        # 次の実行時刻まで待機処理
        now = datetime.now(timezone.utc)
        logger.debug(f"Current time: {now}")

        run_minute = int(timeframe_perp.replace("m", ""))

        # 次の実行時刻を計算（run_minuteの倍数の分に実行）
        current_minute = now.minute
        # current_second = now.second

        # 次の実行分を計算（run_minuteの倍数）
        next_minute = ((current_minute // run_minute) + 1) * run_minute

        if next_minute >= 60:
            # 次の時間に繰り越し
            next_run = (now + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            # 同じ時間内
            next_run = now.replace(minute=next_minute, second=0, microsecond=0)

        wait_seconds = (next_run - now).total_seconds()
        logger.debug(
            f"Waiting for {wait_seconds:.1f} seconds until next run at {next_run} UTC "
            f"(run every {run_minute} minutes: 0, {run_minute}, {run_minute*2}, ...)"
        )
        await asyncio.sleep(wait_seconds)

        # 時間足の取得・登録
        toDateUtc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        fromDateUtc = toDateUtc - timedelta(days=1)  # 過去2分のデータを取得

        logger.info(
            f"[Signal Check] Fetching OHLCV data from {fromDateUtc} to {toDateUtc}"
        )

        # 各シンボルについて処理
        for symbol in perp_symbols:
            try:
                logger.debug(f"Processing {symbol}")

                # 過去1時間のOHLCVデータを取得
                ohlcv = await hyperliquid_exchange.fetch_ohlcv_async(
                    symbol=f"{symbol}",
                    timeframe=timeframe_perp,
                    fromDate=fromDateUtc,
                    toDate=toDateUtc,
                )

                logger.debug(f"Fetched {len(ohlcv)} OHLCV records for {symbol}")
                if ohlcv:
                    logger.debug(
                        f"First OHLCV record timestamp: {ohlcv[0][0]} ({datetime.fromtimestamp(ohlcv[0][0]/1000, tz=timezone.utc)})"
                    )
                    logger.debug(
                        f"Last OHLCV record timestamp: {ohlcv[-1][0]} ({datetime.fromtimestamp(ohlcv[-1][0]/1000, tz=timezone.utc)})"
                    )

                # OHLCVデータの登録
                importer.register_data(f"{symbol}", ohlcv)
                logger.debug(f"Registered OHLCV data for {symbol.upper()}")

                # シグナルチェック
                await check_signal(
                    startDate=fromDateUtc,
                    endDate=toDateUtc,
                    symbol=f"{symbol}",
                    timeframe=timeframe_perp,
                    amountByUSDC=amount_by_usdc,
                )
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue


async def check_trailing_stop(symbol: str, current_price: float) -> None:
    position = trailing_manager.get_position(symbol=symbol)

    if position is None:
        logger.debug(f"No trailing stop position found for {symbol}")
        return

    updated = trailing_manager.update_stoploss_price(
        symbol=symbol,
        current_price=current_price,
    )

    if updated:
        current_tp_sl_info = await hyperliquid_exchange.fetch_tp_sl_info(
            symbol=symbol,
        )

        if current_tp_sl_info is None:
            # ポジションが存在しない場合、TrailingManagerから削除
            logger.warning(
                f"Cannot update trailing stoploss for {symbol}: No TP/SL info found."
                "Removing from TrailingManager."
            )
            trailing_manager.remove_position(symbol=symbol)
            return

        await protection_reconciler.reconcile_symbol(
            symbol=symbol,
            trailing_stop=position.current_stoploss_price,
        )
        logger.info(
            f"Updated trailing stoploss for {symbol} to {position.current_stoploss_price}"
        )


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

    # Repository timestamps are candle open times. Never evaluate the candle
    # whose interval is still in progress, and never execute the same closed
    # symbol/timeframe candle twice in this process.
    try:
        df, candle_identity = latest_closed_identity(
            df,
            symbol=symbol,
            timeframe=timeframe,
            now=endDate,
            required_rows=trading_config.sar_consecutive_count + 1,
        )
    except ValueError as exc:
        logger.warning(f"{symbol}: Candle sequence rejected: {exc}")
        return
    if candle_identity is None:
        logger.debug(f"{symbol}: No closed candle available")
        return
    if not candle_gate.claim(candle_identity):
        logger.debug(
            f"{symbol}: Candle already evaluated: {candle_identity.open_time_ms}"
        )
        return

    current_sar_direction = sar_checker.get_current_sar_direction(df)
    if current_sar_direction is None:
        logger.warning(f"{symbol}: Latest closed candle has ambiguous SAR direction")
        return

    # Get current position for this symbol
    positions = await hyperliquid_exchange.exchange_public.fetch_positions()
    current_position = None
    current_position_side = None
    for pos in positions:
        if pos.get("symbol") == symbol:
            contracts = pos.get("contracts", 0)
            if contracts and float(contracts) != 0:
                current_position = pos
                current_position_side = pos.get("side")  # 'long' or 'short'
                break

    progress = sar_state_store.advance(
        candle=candle_identity,
        direction=current_sar_direction,
        position_side=current_position_side,
    )
    if progress is None:
        logger.debug(
            f"{symbol}: Candle already persisted: {candle_identity.open_time_ms}"
        )
        return
    logger.debug(
        f"{symbol}: SAR direction - Previous: {progress.previous_direction}, "
        f"Current: {progress.current_direction}, "
        f"Opposite count: {progress.opposite_count}"
    )
    sar_close_consecutive_count = trading_config.sar_close_consecutive_count
    should_close_position = (
        current_position is not None
        and progress.opposite_count >= sar_close_consecutive_count
    )

    # Close position if consecutive opposite SAR threshold reached
    if should_close_position:
        logger.info(
            f"{symbol}: Consecutive opposite SAR threshold reached "
            f"({progress.opposite_count}/{sar_close_consecutive_count}). "
            f"Closing {current_position_side} position."
        )
        contracts = abs(float(current_position.get("contracts") or 0))
        close_side = "sell" if current_position_side == "long" else "buy"
        prepared_close = await hyperliquid_exchange.prepare_market_order(
            symbol,
            contracts,
            reference_price=float(current_position.get("markPrice") or 0) or None,
        )
        close_intent = create_intent(
            strategy="sar-close-v1",
            symbol=symbol,
            timeframe=timeframe,
            candle_open_ms=candle_identity.open_time_ms,
            side=close_side,
            amount=prepared_close.amount,
            reduce_only=True,
        )
        close_state = await execution_coordinator.execute_close(close_intent)
        closed_positions = [
            {
                "id": close_state.order_id or close_state.cloid,
                "symbol": symbol,
                "side": close_side,
                "amount": close_state.filled or prepared_close.amount,
                "price": current_position.get("markPrice") or 0.0,
            }
        ]
        trailing_manager.remove_position(symbol=symbol)
        await send_close_position_notification(
            symbol=symbol,
            closed_positions=closed_positions,
            reason=f"Consecutive opposite SAR ({sar_close_consecutive_count}x): position={current_position_side}, SAR={current_sar_direction}",
            timeframe=timeframe,
        )
        # Close and reverse is intentionally two phase. A later pass must
        # re-fetch the exchange position and observe it as flat before a
        # reverse entry can be created.
        return

    if trading_config.signal_mode is SignalMode.SAR_ONLY:
        long_signal = sar_checker.check_long(df)
        short_signal = sar_checker.check_short(df)
        long_reason = "SAR bullish transition" if long_signal else "No long signal"
        short_reason = "SAR bearish transition" if short_signal else "No short signal"
    else:
        long_signal, short_signal, _, price_reason = check_price_change_signal(
            df, trading_config.price_change_threshold_percent
        )
        long_reason = price_reason if long_signal else "No long signal"
        short_reason = price_reason if short_signal else "No short signal"
    if long_signal and short_signal:
        logger.error(f"{symbol}: Conflicting entry signals rejected")
        return

    if long_signal or short_signal:
        logger.info(
            f"{symbol}: Long Signal: {long_signal} ({long_reason}), "
            f"Short Signal: {short_signal} ({short_reason})"
        )
    else:
        logger.debug(f"{symbol}: No signal detected")

    if current_position is not None:
        logger.debug(
            f"{symbol}: Position already exists; entry/add/reverse is inhibited "
            "until the exchange confirms a flat position"
        )
        return

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


async def execute_long_order(
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    amountByUSDC: float,
    reason: str = "",
) -> None:
    """Place a long entry and do not return until exchange protection is proven."""
    logger.info(f"{symbol}: Long signal detected! Placing long order...")
    logger.info(f"{symbol}: Reason: {reason}")

    try:
        # 現在価格を取得
        ticker = await hyperliquid_exchange.fetch_price_async(f"{symbol}")
        current_price = ticker["last"]

        # 注文数量を計算
        prepared = await hyperliquid_exchange.prepare_market_order(
            symbol,
            amountByUSDC / current_price,
            reference_price=current_price,
        )
        amount = prepared.amount

        candle_open_ms = int(
            pd.to_datetime(df.iloc[-1]["timestamp"], utc=True).timestamp() * 1000
        )
        intent = create_intent(
            strategy="sar-price-v1",
            symbol=symbol,
            timeframe=timeframe,
            candle_open_ms=candle_open_ms,
            side="buy",
            amount=amount,
        )
        receipt = await execution_coordinator.execute_entry(
            intent,
            expected_side="long",
        )
        order_state = receipt.order
        current_price = float(receipt.position.get("entryPrice") or 0)
        amount = abs(float(receipt.position.get("contracts") or 0))
        order_result = {"id": order_state.order_id or order_state.cloid}
        logger.success(f"Created and protected long position for {symbol}")

        # トレーリングストップ管理の更新
        # 既存ポジションがあればトレーリング状態を引き継ぎ、オーダーIDのみ更新
        current_tp_sl_info = await hyperliquid_exchange.fetch_tp_sl_info(
            symbol=symbol,
        )
        if current_tp_sl_info is not None:
            trailing_manager.add_or_update_position(
                symbol=symbol,
                side=PositionSide.LONG,
                entry_price=current_price,
                contracts=amount,
                stoploss_order_id=current_tp_sl_info.stop_loss_order_id,
                initial_stoploss_price=current_tp_sl_info.stop_loss_trigger_price,
            )
        else:
            logger.error(f"{symbol}: Entry accepted but TP/SL is not visible yet")

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
    """Place a short entry and do not return until exchange protection is proven."""
    logger.info(f"{symbol}: Short signal detected! Placing short order...")
    logger.info(f"{symbol}: Reason: {reason}")

    try:
        # 現在価格を取得
        ticker = await hyperliquid_exchange.fetch_price_async(f"{symbol}")
        current_price = ticker["last"]

        # 注文数量を計算
        prepared = await hyperliquid_exchange.prepare_market_order(
            symbol,
            amountByUSDC / current_price,
            reference_price=current_price,
        )
        amount = prepared.amount

        candle_open_ms = int(
            pd.to_datetime(df.iloc[-1]["timestamp"], utc=True).timestamp() * 1000
        )
        intent = create_intent(
            strategy="sar-price-v1",
            symbol=symbol,
            timeframe=timeframe,
            candle_open_ms=candle_open_ms,
            side="sell",
            amount=amount,
        )
        receipt = await execution_coordinator.execute_entry(
            intent,
            expected_side="short",
        )
        order_state = receipt.order
        current_price = float(receipt.position.get("entryPrice") or 0)
        amount = abs(float(receipt.position.get("contracts") or 0))
        order_result = {"id": order_state.order_id or order_state.cloid}
        logger.success(f"Created and protected short position for {symbol}")

        # トレーリングストップ管理の更新
        # 既存ポジションがあればトレーリング状態を引き継ぎ、オーダーIDのみ更新
        current_tp_sl_info = await hyperliquid_exchange.fetch_tp_sl_info(
            symbol=symbol,
        )

        if current_tp_sl_info is not None:
            trailing_manager.add_or_update_position(
                symbol=symbol,
                side=PositionSide.SHORT,
                entry_price=current_price,
                contracts=amount,
                stoploss_order_id=current_tp_sl_info.stop_loss_order_id,
                initial_stoploss_price=current_tp_sl_info.stop_loss_trigger_price,
            )
        else:
            logger.error(f"{symbol}: Entry accepted but TP/SL is not visible yet")

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
        fields.append(
            {
                "name": "🔍 シグナル理由",
                "value": f"`{reason}`",
                "inline": False,
            }
        )

    # その他のフィールドを追加
    fields.extend(
        [
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
        ]
    )

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

            position_details.append(
                {
                    "side": side,
                    "contracts": contracts,
                    "price": price,
                    "order_id": order_id,
                }
            )

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
            embed["fields"].append(
                {
                    "name": f"Position #{i} - {detail['side'].upper()}",
                    "value": (
                        f"数量: `{detail['contracts']}`\n"
                        f"価格: `{detail['price']}`\n"
                        f"Order ID: `{detail['order_id']}`"
                    ),
                    "inline": True,
                }
            )

        await notificator.send_notification_embed_with_file(
            message="", embeds=[embed], image_buffers=[]
        )
        logger.info(f"Close position notification sent for {symbol}")

    except Exception as e:
        logger.error(f"Error sending close position notification for {symbol}: {e}")


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


async def main() -> None:
    """メインエントリーポイント: 複数の非同期タスクを並行実行"""
    logger.info(
        f"Starting crypto perp collector application on {trading_config.network.value}"
    )
    supervisor = RuntimeSupervisor(
        [hyperliquid_exchange],
        on_shutdown_requested=order_executor.stop_accepting,
    )
    supervisor.install_signal_handlers()

    try:
        recovered_orders = await order_executor.recover_unsettled()
        unresolved = [
            order
            for order in recovered_orders
            if order.status
            not in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        ]
        if unresolved:
            raise RuntimeError(
                "startup is inhibited by unresolved order intent(s): "
                + ", ".join(order.cloid for order in unresolved)
            )

        # 起動時にTrailingManagerを初期化（既存ポジションを取得）
        await initialize_trailing_manager()

        # WebSocket接続を確立（サブスクリプションの前に接続が必要）
        if hyperliquid_exchange.ws_client.ws is None:
            await hyperliquid_exchange.ws_client.connect()
            logger.info("WebSocket connected before subscriptions")

        await notificator.send_notification_async(
            message=(
                "Hyperliquid bot started: "
                f"network={trading_config.network.value}, symbols={len(perp_symbols)}"
            ),
            files=[],
        )

        await supervisor.run(
            [
                hyperliquid_exchange.start_ws_listener(),
                signal_check_loop(),
                trailing_stop_loop(),
                close_position_notification_loop(),
                heartbeat_loop(),
            ]
        )
    except Exception as exc:
        logger.exception(f"Fatal runtime error: {type(exc).__name__}")
        await notificator.send_notification_async(
            message=f"Hyperliquid bot fatal error: {type(exc).__name__}", files=[]
        )
        raise
    finally:
        try:
            await notificator.send_notification_async(
                message="Hyperliquid bot shutdown complete.", files=[]
            )
        finally:
            await supervisor.close()
        logger.info("Application shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
