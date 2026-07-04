"""
utils/embeds.py
===============
Centralized embed builder.

All of the bot's visual style is defined here so there is no code
duplication and the look can be changed from a single point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import discord

if TYPE_CHECKING:
    from main import GeneratorBot


def _parse_color(color_str: str) -> discord.Color:
    """Converts a color string ('#5865F2', '5865F2', '0x5865F2') to discord.Color."""
    if not color_str:
        return discord.Color.blurple()
    color_str = color_str.strip().lstrip("#").removeprefix("0x")
    try:
        return discord.Color(int(color_str, 16))
    except ValueError:
        return discord.Color.blurple()


def build_stock_embed(
    bot: "GeneratorBot",
    stock_info: List[Tuple[str, int]],
    total: int,
) -> discord.Embed:
    """
    Builds the embed that shows the available stock.

    Parameters
    ----------
    bot : Bot instance (to access the config).
    stock_info : List of (category, amount) tuples.
    total : Total products summed across all categories.
    """
    config = bot.config
    color = _parse_color(config.get("embed_color", "#5865F2"))
    emojis: dict = config.get("emojis", {}) or {}

    embed = discord.Embed(
        title=config.get("title", "📦 Available Stock"),
        description=config.get("description", "Available products:"),
        color=color,
        timestamp=discord.utils.utcnow(),
    )

    if not stock_info:
        embed.add_field(
            name="⚠️ Out of stock",
            value="There are currently no products available.",
            inline=False,
        )
    else:
        for category, amount in stock_info:
            emoji = emojis.get(category, "•")
            embed.add_field(
                name=f"{emoji} `{category}`",
                value=f"**{amount}** units available",
                inline=True,
            )

    embed.add_field(
        name="📊 Total",
        value=f"**{total}** products",
        inline=False,
    )

    embed.set_footer(text=config.get("footer", "Generator Bot"))
    return embed


def build_success_embed(bot: "GeneratorBot", category: str) -> discord.Embed:
    """Ephemeral confirmation embed after a successful /claim."""
    config = bot.config
    emojis: dict = config.get("emojis", {}) or {}
    emoji = emojis.get(category, "✅")

    embed = discord.Embed(
        title=f"{emoji} Claim successful",
        description=(
            f"**{category}** has been sent to your direct messages.\n"
            f"Check your DMs to get your product."
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=config.get("footer", "Generator Bot"))
    return embed


def build_error_embed(title: str, description: str) -> discord.Embed:
    """Generic ephemeral error embed."""
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Generator Bot")
    return embed


def build_dm_embed(bot: "GeneratorBot", category: str) -> discord.Embed:
    """Embed that accompanies the product delivered via DM."""
    config = bot.config
    color = _parse_color(config.get("embed_color", "#5865F2"))
    emojis: dict = config.get("emojis", {}) or {}
    emoji = emojis.get(category, "🎁")

    embed = discord.Embed(
        title=f"{emoji} Delivery: {category}",
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=config.get("footer", "Generator Bot"))
    return embed


def build_admin_embed(title: str, description: str, color: discord.Color = None) -> discord.Embed:
    """Embed for admin action confirmations."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Generator Bot • Admin")
    return embed
