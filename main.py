"""
main.py
=======
Entry point of the Generator Bot (Discord, discord.py 2.x).

Usage:
    pip install -r requirements.txt
    python main.py

Before running, edit config.json and put your token in the "token" field.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict

import discord
from discord import app_commands
from discord.ext import commands

# Make local packages importable when running `python main.py` directly.
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.logger import DiscordLogger, get_logger  # noqa: E402
from utils.stock_manager import StockManager  # noqa: E402
from utils.embeds import build_error_embed  # noqa: E402

_log = get_logger()


class GeneratorBot(commands.Bot):
    """Custom bot with config and stock loaded at startup."""

    def __init__(self, config: Dict, stock: StockManager) -> None:
        # Required intents: slash commands don't need message_content, but
        # 'guilds' and 'members' are useful for resolving channels/roles.
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
        )
        self.config: Dict = config
        self.stock: StockManager = stock
        self.discord_logger: DiscordLogger = DiscordLogger(self)

    async def setup_hook(self) -> None:
        """Loads cogs and syncs slash commands globally."""
        _log.info("Loading cogs...")
        for cog_file in (BASE_DIR / "commands").glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            ext = f"commands.{cog_file.stem}"
            try:
                await self.load_extension(ext)
            except Exception as exc:
                _log.error("Could not load cog '%s': %s", ext, exc)

        # Sync slash commands globally.
        # The first sync may take up to 1h to propagate to all servers.
        # For instant dev sync in a specific server, use:
        #   self.tree.copy_global_to(guild=<Guild>)
        #   await self.tree.sync(guild=<Guild>)
        try:
            synced = await self.tree.sync()
            _log.info("Synced %d slash commands.", len(synced))
        except Exception as exc:
            _log.error("Error syncing slash commands: %s", exc)

    @property
    def bot_name(self) -> str:
        return self.config.get("bot_name", "Generator Bot")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config() -> Dict:
    """Loads config.json and validates the minimum required fields."""
    config_path = BASE_DIR / "config.json"
    if not config_path.exists():
        _log.error("config.json not found at %s", config_path)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if not config.get("token") or config["token"] == "PUT_YOUR_TOKEN_HERE":
        _log.error(
            "You have not configured the token in config.json. "
            "Edit the 'token' field with your bot token."
        )
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    config = load_config()
    stock_path = str(BASE_DIR / "stock.json")
    stock = StockManager(stock_path)

    bot = GeneratorBot(config=config, stock=stock)

    @bot.event
    async def on_ready() -> None:
        _log.info("✅ Connected as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        _log.info("Bot: %s", bot.bot_name)
        _log.info("------")
        if bot.user:
            try:
                await bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name="stock • /stock • /claim",
                    ),
                )
            except discord.DiscordException as exc:
                _log.warning("Could not change presence: %s", exc)

    # Global error handler for slash commands.
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        _log.error("Error in app_command: %s", error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=build_error_embed(
                        "Unexpected error",
                        "An error occurred while processing the command. Please try again.",
                    ),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=build_error_embed(
                        "Unexpected error",
                        "An error occurred while processing the command. Please try again.",
                    ),
                    ephemeral=True,
                )
        except discord.DiscordException:
            pass

    try:
        await bot.start(config["token"])
    except KeyboardInterrupt:
        _log.info("Shutdown requested by user.")
        await bot.close()
    except Exception as exc:
        _log.error("Fatal error starting the bot: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
