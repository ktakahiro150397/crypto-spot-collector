from io import BytesIO

import discord
import pandas as pd
from discord import app_commands
from discord.ext import commands
from loguru import logger

from crypto_spot_collector.exchange import IExchange
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository
from crypto_spot_collector.utils.pnl import create_pnl_plot


class PnLBybitCog(commands.Cog):
    def __init__(self, bot: commands.Bot, exchange: IExchange) -> None:
        self.bot = bot
        self.exchange = exchange

    @app_commands.command(name="pnl", description="Gets the profit and loss statement.")
    async def pnl(self, interaction: discord.Interaction) -> None:
        try:

            await interaction.response.defer()  # 応答を遅延させる

            with TradeDataRepository() as tradeRepo:
                result = await create_pnl_plot(
                    exchange=self.exchange,
                    tradeRepo=tradeRepo
                )

                free_usdt = await self.exchange.fetch_free_usdt_async()
                embed = discord.Embed(
                    title="PnL Statement",
                    color=0x00ff00 if result.total_pnl >= 0 else 0xff0000,
                    timestamp=interaction.created_at
                )
                for _, row in result.df.iterrows():
                    symbol = row['Symbol']
                    pnl = row['PnL']
                    pnl_percent = (pnl / (row['Current_Value'] - pnl)
                                   ) * 100 if (row['Current_Value'] - pnl) != 0 else 0
                    embed.add_field(
                        name=symbol,
                        value=f"{pnl:+.2f} USDT({pnl_percent:+.2f}%)",
                        inline=True
                    )

                message = f"Total Portfolio Value: {result.total_current_value:.2f} USDT\nTotal PnL: {result.total_pnl:+.2f} USDT({result.total_pnl_percent:+.2f}%)\nFree USDT: {free_usdt:.2f} USDT"
                await interaction.followup.send(message, embed=embed, file=discord.File(result.img_buffer, "pnl_statement.png"))
                logger.info("PnL statement sent successfully")
        except Exception as e:
            logger.error(f"Error in PnL command: {e}")
            await interaction.followup.send("An error occurred while generating the PnL statement.")


async def setup(bot: commands.Bot) -> None:
    bybit_exchange = bot.bybit_exchange  # type: ignore
    await bot.add_cog(PnLBybitCog(bot, bybit_exchange))
