import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
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

logger.info("Configuration loaded successfully")


async def main() -> None:
    hyperliquid_exchange = HyperLiquidExchange(
        mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
        apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
        privateKey=secrets["hyperliquid"]["privatekey"],
    )

    # currencies = await hyperliquid_exchange.fetch_currency_async()
    # logger.info(f"Fetched {len(currencies)} currencies from HyperLiquid")
    # for currency in currencies.values():
    #     logger.info(f"Currency: {currency['code']}, Details: {currency}")

    # free_usdt = await hyperliquid_exchange.fetch_free_usdt_async()
    # logger.info(f"Free USDC balance: {free_usdt}")

    # tickers = await hyperliquid_exchange.exchange_public.fetch_tickers()
    # logger.info(f"Fetched {len(tickers)} tickers from HyperLiquid")
    # for symbol, ticker in tickers.items():
    #     logger.info(f"Ticker: {symbol}")

    # for feature in hyperliquid_exchange.exchange_public.features:
    #     logger.info(f"{feature}")

    symbol = "XRP/USDC:USDC"
    price = 2.19
    amount = 5.0

    order_result = await hyperliquid_exchange.create_order_perp_long_async(
        symbol=symbol,
        amount=amount,
        price=price,
    )
    logger.info(f"Perpetual long order result: {order_result}")

    await hyperliquid_exchange.close()

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
