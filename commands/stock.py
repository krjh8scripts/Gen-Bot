"""
commands/stock.py
=================
Cog implementing the /stock slash command.

Shows a modern embed with:
  - Name of each category.
  - Available amount.
  - Total products.
  - Configurable color / footer / title / description.
  - Automatic timestamp.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_stock_embed
from utils.logger import get_logger

_log = get_logger()


class StockCog(commands.Cog):
    """/stock command — shows the available stock."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stock",
        description="Shows the available stock of all products.",
    )
    async def stock(self, interaction: discord.Interaction) -> None:
        """Shows an embed with the current stock."""
        stock_info = await self.bot.stock.get_stock_info()
        total = await self.bot.stock.get_total()

        embed = build_stock_embed(self.bot, stock_info, total)
        _log.info(
            "%s (id=%s) checked the stock. Total: %d",
            interaction.user, interaction.user.id, total,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Cog entry point. Adds it to the bot."""
    await bot.add_cog(StockCog(bot))
    _log.info("Cog 'StockCog' loaded.")
