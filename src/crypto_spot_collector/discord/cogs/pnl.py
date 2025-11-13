from io import BytesIO

import discord
import pandas as pd
from discord import app_commands
from discord.ext import commands
from loguru import logger
from matplotlib import pyplot as plt

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.trade_data_repository import TradeDataRepository


class PnLBybitCog(commands.Cog):
    def __init__(self, bot: commands.Bot, exchange: BybitExchange) -> None:
        self.bot = bot
        self.exchange = exchange

    @app_commands.command(name="pnl", description="Gets the profit and loss statement.")
    async def greet(self, interaction: discord.Interaction) -> None:
        try:

            await interaction.response.defer()  # 応答を遅延させる

            portfolio = self.exchange.get_spot_portfolio()
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

            if len(portfolio) == 0:
                await interaction.followup.send("No assets in the portfolio.")
            else:

                logger.debug("Generating PnL statement chart")
                df = pd.DataFrame(
                    [
                        {
                            "Symbol": asset.symbol,
                            "Total_Amount": asset.total_amount,
                            "Current_Value": asset.current_value,
                            "PnL": asset.profit_loss,
                        }
                        for asset in portfolio if asset.symbol != "USDT"
                    ]
                )
                total_current_value = df['Current_Value'].sum()
                total_pnl = df['PnL'].sum()
                total_pnl_percent = (total_pnl / (total_current_value - total_pnl)) * \
                    100 if (total_current_value - total_pnl) != 0 else 0
                logger.debug(
                    f"Total Current Value: {total_current_value}, Total PnL: {total_pnl}({total_pnl_percent:+.2f}%)")

                # サブプロットの作成
                fig, axes = plt.subplots(1, 2, figsize=(15, 6))
                fig.suptitle('Cryptocurrency Portfolio Analysis', fontsize=16)

                # 1. 現在価値の円グラフ(シンボルごと)
                axes[0].pie(df['Current_Value'], labels=df['Symbol'],
                            autopct='%1.1f%%', startangle=140)
                axes[0].set_title('Current Value Distribution by Asset')
                # axes[0].bar(df['Symbol'], df['Current_Value'])
                # axes[0].set_title('Current Value by Asset')
                # axes[0].set_ylabel('Value (USDT)')
                # axes[0].tick_params(axis='x', rotation=45)

                # 2. PnLの棒グラフ（正負で色分け）
                colors = ['green' if x >= 0 else 'red' for x in df['PnL']]
                axes[1].bar(df['Symbol'], df['PnL'], color=colors)
                axes[1].set_title('Profit & Loss by Asset')
                axes[1].set_ylabel('PnL (USDT)')
                axes[1].tick_params(axis='x', rotation=45)
                axes[1].axhline(y=0, color='black', linestyle='-', alpha=0.3)

                plt.tight_layout()

                # 画像をメモリ上に保存
                img_buffer1 = BytesIO()
                plt.savefig(img_buffer1, format="png",
                            dpi=150, bbox_inches="tight")
                img_buffer1.seek(0)

                free_usdt = self.exchange.fetch_free_usdt()
                embed = discord.Embed(
                    title="PnL Statement",
                    color=0x00ff00 if total_pnl >= 0 else 0xff0000,
                    timestamp=interaction.created_at
                )
                for _, row in df.iterrows():
                    symbol = row['Symbol']
                    pnl = row['PnL']
                    pnl_percent = (pnl / (row['Current_Value'] - pnl)
                                   ) * 100 if (row['Current_Value'] - pnl) != 0 else 0
                    embed.add_field(
                        name=symbol,
                        value=f"{pnl:+.2f} USDT({pnl_percent:+.2f}%)",
                        inline=True
                    )

                message = f"Total Portfolio Value: {total_current_value:.2f} USDT\nTotal PnL: {total_pnl:+.2f} USDT({total_pnl_percent:+.2f}%)\nFree USDT: {free_usdt:.2f} USDT"
                await interaction.followup.send(message, embed=embed, file=discord.File(img_buffer1, "pnl_statement.png"))
                logger.info("PnL statement sent successfully")
        except Exception as e:
            logger.error(f"Error in PnL command: {e}")
            await interaction.followup.send("An error occurred while generating the PnL statement.")

    @app_commands.command(name="pnl_detail", description="Gets detailed profit and loss information.")
    async def detail(self, interaction: discord.Interaction) -> None:
        """Detailed PnL command - to be implemented"""
        await interaction.response.defer()

        await interaction.response.send_message("Detailed PnL command is under development.")


async def setup(bot: commands.Bot) -> None:
    bybit_exchange = bot.bybit_exchange  # type: ignore
    await bot.add_cog(PnLBybitCog(bot, bybit_exchange))
