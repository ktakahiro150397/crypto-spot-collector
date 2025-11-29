import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from crypto_spot_collector.apps.import_historical_data import HistoricalDataImporter
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository
from crypto_spot_collector.utils.secrets import load_config

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ログファイル名（日付付き）
log_file = LOG_DIR / \
    f"hyperliquid_perp_{datetime.now().strftime('%Y%m%d')}.log"

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


logger.info("Initializing crypto spot collector script")
secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

repo = OHLCVRepository()
importer = HistoricalDataImporter()


logger.info("Configuration loaded successfully")


async def test_minimal_ws() -> None:
    """最小限のWebSocket購読テスト - candleを購読"""
    import asyncio
    import json
    import time

    import websockets

    ws_url = "wss://api.hyperliquid.xyz/ws"

    async with websockets.connect(ws_url) as websocket:
        # XRPの1分足キャンドルを購読
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "candle",
                "coin": "XRP",
                "interval": "1m"
            }
        }

        await websocket.send(json.dumps(subscription))
        logger.info(f"Sent subscription: {subscription}")

        last_receive_time = None

        # 最初の20メッセージを受信してタイミングを確認
        for i in range(20):
            message = await websocket.recv()
            current_time = time.time()
            data = json.loads(message)

            # 前回からの経過時間を計算
            interval_seconds = None
            if last_receive_time is not None:
                interval_seconds = current_time - last_receive_time
            last_receive_time = current_time

            # subscriptionResponseは簡潔に表示
            if data.get("channel") == "subscriptionResponse":
                logger.info(f"Message #{i+1}: Subscription confirmed")
            else:
                interval_info = f"(+{interval_seconds:.3f}s)" if interval_seconds else ""
                logger.info(
                    f"Message #{i+1} {interval_info} - Channel: {data.get('channel')}")

                # キャンドルデータの場合、詳細を表示
                if data.get("channel") == "candle":
                    candles = data.get("data", [])
                    for candle in candles if isinstance(candles, list) else [candles]:
                        logger.info(
                            f"  Candle: {candle.get('s')} {candle.get('i')} | "
                            f"Time: {candle.get('t')} - {candle.get('T')} | "
                            f"O: {candle.get('o')}, H: {candle.get('h')}, "
                            f"L: {candle.get('l')}, C: {candle.get('c')}, "
                            f"V: {candle.get('v')}, Trades: {candle.get('n')}"
                        )


def handle_candle(candles: Any) -> None:
    """キャンドルデータを受信したときのコールバック"""
    # nonlocal candle_count
    logger.info(f"handle_candle called! Received data: {candles}")
    for candle in candles if isinstance(candles, list) else [candles]:
        # candle_count += 1

        logger.info(f"t : {candle.get('t')}"
                    f"T : {candle.get('T')}"
                    f"o : {candle.get('o')}")

        ohlvc_data = [
            candle.get("t"),  # ミリ秒のまま渡す（register_data内で変換される）
            candle.get("o"),
            candle.get("h"),
            candle.get("l"),
            candle.get("c"),
            candle.get("v"),
        ]

        logger.debug(f"Prepared OHLCV data: {ohlvc_data}")

        result = importer.register_data(
            symbol="XRP_ws",
            data=[ohlvc_data]
        )
        logger.info(f"register_data returned: {result}")

        logger.info(
            f"Symbol: {candle.get('s')}, "
            f"Interval: {candle.get('i')}, "
            f"Open: {candle.get('o')}, "
            f"High: {candle.get('h')}, "
            f"Low: {candle.get('l')}, "
            f"Close: {candle.get('c')}, "
            f"Volume: {candle.get('v')}"
        )

        # logger.info(
        #     f"Candle #{candle_count}: "
        #     f"Time: {candle.get('t')} - {candle.get('T')}, "
        #     f"Symbol: {candle.get('s')}, "
        #     f"Interval: {candle.get('i')}, "
        #     f"Open: {candle.get('o')}, "
        #     f"High: {candle.get('h')}, "
        #     f"Low: {candle.get('l')}, "
        #     f"Close: {candle.get('c')}, "
        #     f"Volume: {candle.get('v')}, "
        #     f"Trades: {candle.get('n')}"
        # )


async def main() -> None:
    # HyperLiquidExchangeのWebSocket機能をテスト
    hyperliquid_exchange = HyperLiquidExchange(
        mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
        apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
        privateKey=secrets["hyperliquid"]["privatekey"],
        take_profit_rate=secrets["settings"]["perpetual"]["take_profit_rate"],
        stop_loss_rate=secrets["settings"]["perpetual"]["stop_loss_rate"],
        leverage=secrets["settings"]["perpetual"]["leverage"],
        testnet=False,  # Use mainnet
    )

    symbol = "XRP/USDC:USDC"

    # WebSocket経由でOHLCVデータを購読するテスト
    candle_count = 0
    max_candles = 10  # 10本のキャンドルを受信したら終了

    logger.info("Starting WebSocket listener task...")

    try:

        logger.info("Subscribing to OHLCV WebSocket...")
        # OHLCVデータを購読（内部でconnectも呼ばれる）
        await hyperliquid_exchange.subscribe_ohlcv_ws(
            symbol=symbol,
            interval="1m",
            callback=handle_candle
        )

        # 購読後にリスナーを開始
        listener_task = asyncio.create_task(
            hyperliquid_exchange.start_ws_listener())

        # リスナーが開始するまで少し待つ
        await asyncio.sleep(0.5)

        logger.info(f"Waiting for {max_candles} candles...")
        # 指定数のキャンドルを受信するまで待機
        while candle_count < max_candles:
            logger.debug(f"Candle count: {candle_count}/{max_candles}")
            await asyncio.sleep(1)

        logger.info(
            f"Received {candle_count} candles. Unsubscribing and closing connection.")

        # 購読解除
        await hyperliquid_exchange.unsubscribe_ohlcv_ws(symbol=symbol, interval="1m")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        # クリーンアップ
        await hyperliquid_exchange.close()
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
