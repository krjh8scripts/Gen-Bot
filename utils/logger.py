"""
utils/logger.py
================
Bot logging system.

Automatically logs:
  - User (name#discriminator / global name)
  - User ID
  - Claimed product
  - Time (UTC)
  - Remaining stock for that category

Logs are sent to:
  - Local file: data/bot.log (rotating)
  - Configurable Discord channel (if logs_channel_id is set)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord

if TYPE_CHECKING:
    from main import GeneratorBot


# ---------------------------------------------------------------------------
# Standard Python logger setup (rotating file + console)
# ---------------------------------------------------------------------------

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(_DATA_DIR, exist_ok=True)

_LOG_FILE = os.path.join(_DATA_DIR, "bot.log")

_logger = logging.getLogger("generator_bot")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    _file_handler = RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(
        logging.Formatter(fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    )
    _logger.addHandler(_file_handler)
    _logger.addHandler(_console_handler)


def get_logger() -> logging.Logger:
    """Returns the bot's main logger."""
    return _logger


# ---------------------------------------------------------------------------
# Discord logger: sends claim events to a configurable channel
# ---------------------------------------------------------------------------


class DiscordLogger:
    """Sends structured claim logs to a Discord channel."""

    def __init__(self, bot: "GeneratorBot") -> None:
        self.bot = bot

    @property
    def channel(self) -> Optional[discord.TextChannel]:
        """Configured logs channel, or None if not set."""
        channel_id = self.bot.config.get("logs_channel_id")
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    async def log_claim(
        self,
        user: discord.User | discord.Member,
        product: str,
        item: str,
        remaining: int,
    ) -> None:
        """
        Logs a successful claim.

        Parameters
        ----------
        user : The user who claimed.
        product : The claimed category name.
        item : The delivered item (kept in internal log, hidden from public channel).
        remaining : Remaining stock for that category.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Local file log (full item, for internal audit)
        _logger.info(
            "CLAIM | user=%s id=%s product=%s remaining=%d item=%s",
            user,
            user.id,
            product,
            remaining,
            item,
        )

        # Embed for the Discord channel
        channel = self.channel
        if channel is None:
            _logger.debug("logs_channel_id not configured; skipping Discord log.")
            return

        embed = discord.Embed(
            title="📝 Claim Log",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 User", value=f"{user.mention}\n`{user}`", inline=True)
        embed.add_field(name="🆔 ID", value=f"`{user.id}`", inline=True)
        embed.add_field(name="📦 Product", value=f"**{product}**", inline=True)
        embed.add_field(
            name="⏰ Time (UTC)",
            value=f"`{timestamp}`",
            inline=True,
        )
        embed.add_field(
            name="📊 Remaining stock",
            value=f"`{remaining}` units of `{product}`",
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.set_footer(text=self.bot.config.get("footer", "Generator Bot"))

        try:
            await channel.send(embed=embed)
        except discord.DiscordException as exc:
            _logger.warning("Could not send log to Discord channel: %s", exc)

    async def log_admin_action(
        self,
        admin: discord.User | discord.Member,
        action: str,
        details: str,
    ) -> None:
        """Logs an admin stock action (add/remove/reload)."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        _logger.info(
            "ADMIN | admin=%s id=%s action=%s details=%s",
            admin, admin.id, action, details,
        )

        channel = self.channel
        if channel is None:
            return

        embed = discord.Embed(
            title="🔧 Admin Action",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 Admin", value=f"{admin.mention}\n`{admin}`", inline=True)
        embed.add_field(name="⚙️ Action", value=f"**{action}**", inline=True)
        embed.add_field(name="🆔 Admin ID", value=f"`{admin.id}`", inline=True)
        embed.add_field(name="📝 Details", value=details, inline=False)
        embed.add_field(name="⏰ Time (UTC)", value=f"`{timestamp}`", inline=True)
        embed.set_footer(text=self.bot.config.get("footer", "Generator Bot"))

        try:
            await channel.send(embed=embed)
        except discord.DiscordException as exc:
            _logger.warning("Could not send admin log to Discord channel: %s", exc)
