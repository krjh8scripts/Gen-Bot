"""
commands/claim.py
=================
Cog implementing the /claim <product> slash command.

Flow:
  1. Verifies the product (category) exists.
  2. Verifies there is stock available.
  3. Checks the per-user cooldown.
  4. Verifies the required role (if configured).
  5. Pops the first item from the stock (atomic, with asyncio.Lock).
  6. Tries to send the product via DM.
     - If the DM fails (DMs closed): the item is RESTORED to the stock and the
       user is notified.
     - If the DM succeeds: an ephemeral confirmation is sent in the channel.
  7. The claim is logged (file + Discord channel if configured).

Security:
  - Configurable per-user cooldown.
  - Optional required role.
  - Global lock in StockManager prevents duplicate deliveries.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Dict, List

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_dm_embed, build_error_embed, build_success_embed
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import GeneratorBot

_log = get_logger()


class ClaimCog(commands.Cog):
    """/claim command — claims a product and delivers it via DM."""

    def __init__(self, bot: "GeneratorBot") -> None:
        self.bot = bot
        # In-memory registry of each user's last claim.
        # Key: user_id -> timestamp (monotonic). Resets on bot restart,
        # which is acceptable for a simple cooldown.
        self._last_claim: Dict[int, float] = {}

    # ------------------------------------------------------------------
    # Autocomplete: only suggests products with stock available
    # ------------------------------------------------------------------

    async def product_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        stock_info = await self.bot.stock.get_stock_info()
        # Only categories with stock > 0 are suggested.
        available = [cat for cat, amount in stock_info if amount > 0]
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in available
            if current.lower() in cat.lower()
        ][:25]

    # ------------------------------------------------------------------
    # /claim command
    # ------------------------------------------------------------------

    @app_commands.command(
        name="claim",
        description="Claim a product from the stock. It is delivered via DM.",
    )
    @app_commands.autocomplete(product=product_autocomplete)
    @app_commands.describe(
        product="Product you want to claim (nitro, fortnite, ...)."
    )
    async def claim(
        self,
        interaction: discord.Interaction,
        product: str,
    ) -> None:
        await self._handle_claim(interaction, product)

    # ------------------------------------------------------------------
    # Claim logic
    # ------------------------------------------------------------------

    def _check_cooldown(self, user_id: int) -> float:
        """
        Returns the remaining cooldown seconds for the user.
        0.0 if they can claim right now.
        """
        cooldown = self.bot.config.get("cooldown", 0) or 0
        if cooldown <= 0:
            return 0.0
        last = self._last_claim.get(user_id, 0.0)
        elapsed = time.monotonic() - last
        if elapsed >= cooldown:
            return 0.0
        return cooldown - elapsed

    async def _handle_claim(self, interaction: discord.Interaction, product: str) -> None:
        product = product.strip().lower()

        # 1. Verify required role (if configured).
        role_id = self.bot.config.get("required_role_id")
        if role_id and isinstance(interaction.user, discord.Member):
            if not any(r.id == int(role_id) for r in interaction.user.roles):
                embed = build_error_embed(
                    "No permission",
                    "You do not have the required role to use this command.",
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # 2. Check cooldown.
        remaining_cd = self._check_cooldown(interaction.user.id)
        if remaining_cd > 0:
            embed = build_error_embed(
                "On cooldown",
                f"You must wait **{remaining_cd:.1f}s** before claiming again.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 3. Verify the category exists.
        categories = self.bot.stock.get_categories()
        if product not in categories:
            embed = build_error_embed(
                "Product does not exist",
                f"The product `{product}` does not exist.\n"
                f"Available products: {', '.join(f'`{c}`' for c in categories) or 'none'}.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 4. Verify stock available (quick read, no pop yet).
        count = await self.bot.stock.get_category_count(product)
        if count <= 0:
            embed = build_error_embed(
                "Out of stock",
                f"Sorry, there is no stock available for `{product}` at the moment.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 5. Notify that the request is being processed (DM may take a moment).
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 6. Pop the first item (atomic and saved to disk).
        item = await self.bot.stock.pop_item(product)
        if item is None:  # double check: someone may have claimed between step 4 and here.
            embed = build_error_embed(
                "Out of stock",
                f"Someone claimed the last unit of `{product}` just before you. "
                "Please try again later.",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # 7. Try to deliver via DM.
        dm_sent = await self._send_dm(interaction.user, product, item)

        if not dm_sent:
            # 7a. DM failed: restore the item to the stock so it is not lost.
            await self.bot.stock.restore_item(product, item)
            embed = build_error_embed(
                "Could not deliver",
                "You have your **direct messages closed** and I could not send you the product.\n"
                "Enable the *«Allow direct messages from server members»* option "
                "in your Discord settings and try again.\n\n"
                "The stock has **not** been affected.",
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            _log.warning(
                "DM failed for %s (id=%s). Item restored to '%s'.",
                interaction.user, interaction.user.id, product,
            )
            return

        # 8. Success: register cooldown, ephemeral confirmation, log.
        self._last_claim[interaction.user.id] = time.monotonic()
        remaining = await self.bot.stock.get_category_count(product)
        success_embed = build_success_embed(self.bot, product)
        await interaction.followup.send(embed=success_embed, ephemeral=True)

        await self.bot.discord_logger.log_claim(
            interaction.user, product, item, remaining
        )

    # ------------------------------------------------------------------
    # DM delivery with the product's custom message
    # ------------------------------------------------------------------

    async def _send_dm(
        self,
        user: discord.User | discord.Member,
        product: str,
        item: str,
    ) -> bool:
        """
        Sends the product via DM.

        Returns True if sent successfully, False if the DM failed
        (e.g. the user has DMs closed).
        """
        messages: dict = self.bot.config.get("messages", {}) or {}
        default_msg = self.bot.config.get(
            "default_message", "Here is your product:\n\n{ITEM}"
        )
        # Look up the message by exact category; fall back to default.
        template = messages.get(product) or default_msg
        try:
            content = template.replace("{ITEM}", item)
        except Exception as exc:  # pragma: no cover - defense against weird templates
            _log.error("Error formatting message for '%s': %s", product, exc)
            content = f"Here is your **{product}** product:\n\n```\n{item}\n```"

        try:
            dm_channel = await user.create_dm()
            embed = build_dm_embed(self.bot, product)
            await dm_channel.send(content=content, embed=embed)
            return True
        except discord.Forbidden:
            # DMs closed / the user has blocked the bot.
            return False
        except discord.DiscordException as exc:
            _log.error("Unexpected error sending DM to %s: %s", user, exc)
            return False


async def setup(bot: commands.Bot) -> None:
    """Cog entry point."""
    await bot.add_cog(ClaimCog(bot))
    _log.info("Cog 'ClaimCog' loaded (cooldown=%ss).", bot.config.get("cooldown", 0))
