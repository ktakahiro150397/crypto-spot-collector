import asyncio
import sys
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands, tasks
from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange

# from crypto_spot_collector.discord.cogs.greet import GreetCog
from crypto_spot_collector.utils.secrets import load_secrets

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

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
secrets = load_secrets(secret_file)

BOT_TOKEN = secrets["settings"]["discordBotToken"]


@bot.event
async def on_ready() -> None:
    logger.info(f"Bot is ready. Version : {bot.version}")
    logger.info(f'{bot.user} がログインしました')
    # Cogを読み込んだ後に同期するのが確実
    await bot.tree.sync()
    logger.info("コマンドが同期されました")

    # Start the activity update task
    if not update_activity.is_running():
        update_activity.start()
        logger.info("Activity update task started")


@tasks.loop(hours=1)
async def update_activity() -> None:
    """Update bot activity with PnL information every hour"""
    try:
        logger.info("Updating bot activity with PnL information")

        # Get portfolio data
        portfolio = bot.bybit_exchange.get_spot_portfolio()  # type: ignore

        # Calculate total PnL
        total_pnl = sum(
            asset.profit_loss
            for asset in portfolio
            if asset.symbol != "USDT"
        )
        total_current_value = sum(
            asset.current_value
            for asset in portfolio
            if asset.symbol != "USDT"
        )

        # Calculate PnL percentage
        total_pnl_percent = 0.0
        if total_current_value > 0 and (total_current_value - total_pnl) != 0:
            total_pnl_percent = (
                total_pnl / (total_current_value - total_pnl)
            ) * 100

        # Format activity string
        pnl_str = f"{total_pnl:+.2f}"
        pnl_pct_str = f"{total_pnl_percent:+.2f}"
        activity_text = (
            f"PnL : {pnl_str} USDT ({pnl_pct_str}%) | "
            f"Version : {bot.version}"  # type: ignore
        )

        activity = discord.CustomActivity(name=activity_text)
        await bot.change_presence(activity=activity)

        logger.info(f"Activity updated: {activity_text}")
    except Exception as e:
        logger.error(f"Error updating bot activity: {e}")


@update_activity.before_loop
async def before_update_activity() -> None:
    """Wait for the bot to be ready before starting the task"""
    await bot.wait_until_ready()
    logger.info("Bot is ready, activity update task will begin")


async def main() -> None:
    # 拡張機能（Cog）を読み込む

    bot.bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )  # type: ignore
    bot.version = secrets["settings"]["version"]

    # await bot.load_extension("crypto_spot_collector.discord.cogs.greet")
    await bot.load_extension("crypto_spot_collector.discord.cogs.pnl")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
