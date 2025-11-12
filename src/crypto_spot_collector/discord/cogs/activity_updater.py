from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks
from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository


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
            free_usdt = self.exchange.fetch_free_usdt()

            with TradeDataRepository() as repo:
                for asset in portfolio:
                    holdings, avg_price = repo.get_current_position_and_avg_price(
                        symbol=asset.symbol
                    )
                    current_price = 1.0
                    if asset.symbol != "USDT":
                        current_price = float(
                            self.exchange.fetch_price(
                                f"{asset.symbol}/USDT")["last"]
                        )
                    asset.total_amount = holdings
                    asset.current_value = holdings * current_price
                    asset.profit_loss = asset.current_value - \
                        (holdings * avg_price)

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
            pnl_str = f"{total_pnl:+.2f} USDT"
            pnl_pct_str = f"{total_pnl_percent:+.2f}"
            jst_time_str = datetime.now(timezone.utc).astimezone(
                timezone(timedelta(hours=9))).strftime('%H:%M')

            activity_text = (
                f"PnL : {pnl_str} ({pnl_pct_str}%) | "
                f"Version : {self.bot.version}"  # type: ignore
            )

            activity = discord.CustomActivity(name=activity_text)
            await self.bot.change_presence(activity=activity)

            # Update the bot's application description
            if self.bot.application is not None:
                description_text = (
                    f"PnL : {pnl_str} ({pnl_pct_str}%)\n"
                    f"--- Portfolio Details ---\n"
                )
                description_text += f"Free USDT : ${free_usdt:.2f}\n\n"
                for asset in portfolio:
                    if asset.symbol != "USDT":
                        # Calculate PnL percentage relative to purchase price
                        pnl_percent = (
                            asset.profit_loss /
                            (asset.current_value - asset.profit_loss)
                        ) * 100 if (asset.current_value - asset.profit_loss) != 0 else 0
                        description_text += (
                            f"{asset.symbol:<4} : {pnl_percent:>+6.2f}%\n"
                        )

                description_text += "\n\n"
                # type: ignore
                description_text += f"Version : {self.bot.version}\n"
                description_text += f"Updated On {jst_time_str}"

                await self.bot.application.edit(description=description_text)
                logger.debug(
                    f"Bot application description updated : {description_text}")

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
