import discord
from discord import app_commands
from discord.ext import commands


class GreetCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="greet", description="Sends a greeting message.")
    async def greet(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Hello! Welcome to the server!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GreetCog(bot))
