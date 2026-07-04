"""
commands/admin.py
=================
Admin cog for expanding and managing the stock at runtime.

Commands (restricted to users listed in config["admin_ids"]):
  - /addstock <category> <item>          Adds a single item to a category.
  - /bulkadd <category> <items>          Adds multiple items (one per line).
  - /createcategory <name>               Creates a new empty category.
  - /deletecategory <category>           Deletes a category entirely.
  - /clearcategory <category>            Removes all items but keeps the category.
  - /reloadstock                          Reloads stock.json from disk.

These commands make the bot fully expandable: you can add new product
categories and items directly from Discord without editing any file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_admin_embed, build_error_embed
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import GeneratorBot

_log = get_logger()


def _is_admin(bot: "GeneratorBot", user: discord.User | discord.Member) -> bool:
    """Returns True if the user is in the admin_ids list."""
    admin_ids = bot.config.get("admin_ids", []) or []
    return user.id in [int(aid) for aid in admin_ids]


class AdminCog(commands.Cog):
    """Admin-only commands for expanding the stock."""

    def __init__(self, bot: "GeneratorBot") -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Shared pre-check: only admins can use any command in this cog.
    # ------------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _is_admin(self.bot, interaction.user):
            embed = build_error_embed(
                "Access denied",
                "You must be a bot admin to use these commands.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    # ------------------------------------------------------------------
    # Autocomplete for category-related commands
    # ------------------------------------------------------------------

    async def category_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        categories = self.bot.stock.get_categories()
        return [
            app_commands.Choice(name=cat, value=cat)
            for cat in categories
            if current.lower() in cat.lower()
        ][:25]

    # ------------------------------------------------------------------
    # /addstock  —  add a single item
    # ------------------------------------------------------------------

    @app_commands.command(
        name="addstock",
        description="[Admin] Add a single item to a stock category.",
    )
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.describe(
        category="Category to add the item to (creates it if it does not exist).",
        item="The item to add (e.g. a code or email:password).",
    )
    async def addstock(
        self,
        interaction: discord.Interaction,
        category: str,
        item: str,
    ) -> None:
        category = category.strip().lower()
        item = item.strip()
        if not item:
            await interaction.response.send_message(
                embed=build_error_embed("Invalid input", "The item cannot be empty."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        count = await self.bot.stock.add_item(category, item)
        embed = build_admin_embed(
            "✅ Item added",
            f"Item added to `{category}`.\nThat category now has **{count}** item(s) in stock.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "ADD_ITEM",
            f"Added 1 item to `{category}`. New total: {count}.",
        )

    # ------------------------------------------------------------------
    # /bulkadd  —  add many items at once
    # ------------------------------------------------------------------

    @app_commands.command(
        name="bulkadd",
        description="[Admin] Add multiple items to a stock category (one per line).",
    )
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.describe(
        category="Category to add the items to (creates it if it does not exist).",
        items="Items separated by new lines. They will be appended to the category.",
    )
    async def bulkadd(
        self,
        interaction: discord.Interaction,
        category: str,
        items: str,
    ) -> None:
        category = category.strip().lower()
        item_list = [line.strip() for line in items.splitlines() if line.strip()]
        if not item_list:
            await interaction.response.send_message(
                embed=build_error_embed(
                    "Invalid input", "You must provide at least one item."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        added = len(item_list)
        count = await self.bot.stock.add_items_bulk(category, item_list)
        embed = build_admin_embed(
            "✅ Bulk add complete",
            f"Added **{added}** item(s) to `{category}`.\n"
            f"That category now has **{count}** item(s) in stock.",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "BULK_ADD",
            f"Added {added} item(s) to `{category}`. New total: {count}.",
        )

    # ------------------------------------------------------------------
    # /createcategory  —  create a new empty category
    # ------------------------------------------------------------------

    @app_commands.command(
        name="createcategory",
        description="[Admin] Create a new empty stock category.",
    )
    @app_commands.describe(
        name="Name of the new category (lowercase, no spaces).",
    )
    async def createcategory(
        self,
        interaction: discord.Interaction,
        name: str,
    ) -> None:
        name = name.strip().lower().replace(" ", "_")
        if not name:
            await interaction.response.send_message(
                embed=build_error_embed("Invalid name", "The category name cannot be empty."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        created = await self.bot.stock.create_category(name)
        if created:
            embed = build_admin_embed(
                "✅ Category created",
                f"The category `{name}` has been created (empty).",
            )
        else:
            embed = build_error_embed(
                "Category exists",
                f"The category `{name}` already exists.",
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "CREATE_CATEGORY",
            f"Created category `{name}` (already existed: {not created}).",
        )

    # ------------------------------------------------------------------
    # /deletecategory  —  delete a category entirely
    # ------------------------------------------------------------------

    @app_commands.command(
        name="deletecategory",
        description="[Admin] Delete a stock category and ALL its items.",
    )
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.describe(
        category="Category to delete (cannot be undone).",
    )
    async def deletecategory(
        self,
        interaction: discord.Interaction,
        category: str,
    ) -> None:
        category = category.strip().lower()

        # Capture count before deletion for the log.
        before = await self.bot.stock.get_category_count(category)

        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await self.bot.stock.delete_category(category)
        if deleted:
            embed = build_admin_embed(
                "🗑️ Category deleted",
                f"The category `{category}` has been deleted (it had **{before}** item(s)).",
                color=discord.Color.red(),
            )
        else:
            embed = build_error_embed(
                "Category not found",
                f"The category `{category}` does not exist.",
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "DELETE_CATEGORY",
            f"Deleted category `{category}` (had {before} item(s)).",
        )

    # ------------------------------------------------------------------
    # /clearcategory  —  remove items but keep the category
    # ------------------------------------------------------------------

    @app_commands.command(
        name="clearcategory",
        description="[Admin] Remove all items from a category but keep the category.",
    )
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.describe(
        category="Category to clear.",
    )
    async def clearcategory(
        self,
        interaction: discord.Interaction,
        category: str,
    ) -> None:
        category = category.strip().lower()

        await interaction.response.defer(ephemeral=True, thinking=True)
        removed = await self.bot.stock.clear_category(category)
        if removed > 0:
            embed = build_admin_embed(
                "🧹 Category cleared",
                f"Removed **{removed}** item(s) from `{category}`. "
                f"The category itself has been kept.",
                color=discord.Color.orange(),
            )
        else:
            embed = build_error_embed(
                "Nothing to clear",
                f"The category `{category}` does not exist or is already empty.",
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "CLEAR_CATEGORY",
            f"Cleared {removed} item(s) from `{category}`.",
        )

    # ------------------------------------------------------------------
    # /reloadstock  —  reload stock.json from disk
    # ------------------------------------------------------------------

    @app_commands.command(
        name="reloadstock",
        description="[Admin] Reload stock.json from disk (useful after manual edits).",
    )
    async def reloadstock(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.stock.reload()
        total = await self.bot.stock.get_total()
        info = await self.bot.stock.get_stock_info()
        categories_str = ", ".join(f"`{c}` ({n})" for c, n in info) or "none"
        embed = build_admin_embed(
            "🔄 Stock reloaded",
            f"Stock reloaded from disk.\n**{total}** products across "
            f"{len(info)} categories:\n{categories_str}",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await self.bot.discord_logger.log_admin_action(
            interaction.user, "RELOAD_STOCK",
            f"Reloaded stock. Total: {total}.",
        )


async def setup(bot: commands.Bot) -> None:
    """Cog entry point."""
    await bot.add_cog(AdminCog(bot))
    _log.info("Cog 'AdminCog' loaded.")
