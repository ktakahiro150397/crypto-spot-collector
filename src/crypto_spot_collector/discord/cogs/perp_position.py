import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from crypto_spot_collector.exchange import IExchange
from crypto_spot_collector.notification.discord import discordNotification


class PerpetualPositionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, exchange: IExchange) -> None:
        self.bot = bot
        self.exchange = exchange

    @app_commands.command(name="positions", description="現在のポジション情報を取得します。")
    async def positions(self, interaction: discord.Interaction) -> None:
        try:

            await interaction.response.defer()  # 応答を遅延させる

            positions = await self.exchange.fetch_positions_perp_async()
            for position in positions:
                logger.debug(f"Position: {position}")
            embeds = discordNotification.embed_object_create_helper_perp_position(
                positions)

            if len(positions) == 0:
                message = "現在、保持しているポジションはありません。"
            else:
                message = f"{len(embeds)}つのポジションを保持しています！"

            await interaction.followup.send(message, embed=embeds)
        except Exception as e:
            logger.error(f"Error in PnL command: {e}")
            await interaction.followup.send("An error occurred while generating the PnL statement.")


async def setup(bot: commands.Bot) -> None:
    hyperliquid_exchange = bot.hyperliquid_exchange  # type: ignore
    await bot.add_cog(PerpetualPositionCog(bot, hyperliquid_exchange))
