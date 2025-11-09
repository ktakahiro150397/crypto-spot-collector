from datetime import datetime

import discord
from discord.ext import commands, tasks
from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange


class ActivityUpdaterCog(commands.Cog):
    def __init__(self, bot: commands.Bot, exchange: BybitExchange) -> None:
        self.bot = bot
        self.exchange = exchange
        self.update_activity.start()

    async def cog_unload(self) -> None:
        self.update_activity.cancel()

    @tasks.loop(minutes=1)
    async def update_activity(self) -> None:
        """Update bot activity with PnL information every hour"""
        try:
            logger.info("Updating bot activity with PnL information")

            # Get portfolio data
            portfolio = self.exchange.get_spot_portfolio()

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
                f"Update : {datetime.now().strftime('%H:%M')} | "
                f"Version : {self.bot.version}"  # type: ignore
            )

            activity = discord.CustomActivity(name=activity_text)
            await self.bot.change_presence(activity=activity)

            logger.debug(f"Activity updated: {activity_text}")
        except Exception as e:
            logger.error(f"Error updating bot activity: {e}")

    @update_activity.before_loop
    async def before_update_activity(self) -> None:
        """Wait for the bot to be ready before starting the task"""
        await self.bot.wait_until_ready()
        logger.info("Bot is ready, activity update task will begin")


async def setup(bot: commands.Bot) -> None:
    bybit_exchange = bot.bybit_exchange  # type: ignore
    await bot.add_cog(ActivityUpdaterCog(bot, bybit_exchange))
