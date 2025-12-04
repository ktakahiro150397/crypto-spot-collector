import asyncio
import sys
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands
from loguru import logger

from crypto_spot_collector.apps.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.notification.discord import discordNotification

# from crypto_spot_collector.discord.cogs.greet import GreetCog
from crypto_spot_collector.utils.secrets import load_config
from crypto_spot_collector.utils.version import get_version_from_git

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ログファイル名（日付付き）
log_file = LOG_DIR / \
    f"discord_application_{datetime.now().strftime('%Y%m%d')}.log"

logger.info("Initializing crypto perp collector script")
secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

notificator = discordNotification(
    secrets["discord"]["discordWebhookUrlPerpetual"])

# loguruのログ設定
# デフォルトのハンドラーを削除
logger.remove()

# 標準出力にログを表示（INFOレベル以上、docker logsで確認可能）
logger.add(
    sink=sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
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

# ログ設定
# ログフォルダのパスを取得（プロジェクトルート/logs）
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
# ログファイル名（日付付き）
log_file = LOG_DIR / \
    f"discord_application_{datetime.now().strftime('%Y%m%d')}.log"

secret_file = Path(__file__).parent / "secrets.json"
settings_file = Path(__file__).parent / "settings.json"
secrets = load_config(secret_file, settings_file)

BOT_TOKEN = secrets["discord"]["discordBotToken"]


@bot.event
async def on_ready() -> None:
    logger.info(f"Bot is ready. Version : {bot.version}")  # type: ignore
    logger.info(f'{bot.user} がログインしました')
    # Cogを読み込んだ後に同期するのが確実
    await bot.tree.sync()
    logger.info("コマンドが同期されました")


async def main() -> None:
    # 拡張機能（Cog）を読み込む

    bot.bybit_exchange = BybitExchange(   # type: ignore
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )
    bot.hyperliquid_exchange = HyperLiquidExchange(  # type: ignore
        mainWalletAddress=secrets["hyperliquid"]["mainWalletAddress"],
        apiWalletAddress=secrets["hyperliquid"]["apiWalletAddress"],
        privateKey=secrets["hyperliquid"]["privatekey"],
        take_profit_rate=secrets["settings"]["perpetual"]["take_profit_rate"],
        stop_loss_rate=secrets["settings"]["perpetual"]["stop_loss_rate"],
        leverage=secrets["settings"]["perpetual"]["leverage"],
        testnet=False,
    )

    # await bot.load_extension("crypto_spot_collector.discord.cogs.greet")
    bot.version = "xxx"
    await bot.load_extension("crypto_spot_collector.discord.cogs.perp_position")
    await bot.load_extension("crypto_spot_collector.discord.cogs.pnl")
    await bot.load_extension("crypto_spot_collector.discord.cogs.detail")
    await bot.load_extension("crypto_spot_collector.discord.cogs.activity_updater")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
