import asyncio
import sys
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands
from loguru import logger

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


@bot.event
async def on_ready() -> None:
    logger.info(f'{bot.user} がログインしました')
    # Cogを読み込んだ後に同期するのが確実
    await bot.tree.sync()


async def main() -> None:
    # 拡張機能（Cog）を読み込む
    await bot.load_extension("cogs.greet")
    await bot.start("YOUR_BOT_TOKEN")

if __name__ == "__main__":
    asyncio.run(main())
