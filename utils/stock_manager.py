"""
utils/stock_manager.py
======================
Safe, atomic management of the stock.json file.

Features:
  - Read / write protected by asyncio.Lock (prevents simultaneous claims
    and race conditions).
  - Atomic write: writes to a temporary file and then renames it, so the
    original file is never left corrupt even if the bot restarts mid-operation.
  - Never delivers the same item twice: the item is removed from the stock
    BEFORE being sent via DM, and only restored if the DM fails.
  - Expandable: supports adding items, creating new categories, removing
    categories, and bulk imports at runtime through admin commands.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Dict, List, Optional, Tuple

from .logger import get_logger

_log = get_logger()


class StockManager:
    """Async-safe stock handler with full CRUD support."""

    def __init__(self, stock_path: str) -> None:
        self.stock_path: str = stock_path
        self._lock: asyncio.Lock = asyncio.Lock()
        self._cache: Dict[str, List[str]] = {}
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Disk load / save
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> None:
        """Loads stock from the JSON file. Creates an empty one if missing."""
        if not os.path.exists(self.stock_path):
            _log.warning("stock.json not found. Creating an empty one at %s", self.stock_path)
            self._cache = {}
            self._save_to_disk()
            return

        try:
            with open(self.stock_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Stock JSON must be an object with categories.")
            # Normalize: each value must be a list of strings.
            self._cache = {
                str(k): [str(item) for item in v]
                for k, v in data.items()
                if isinstance(v, list)
            }
            _log.info("Stock loaded: %d categories.", len(self._cache))
        except (json.JSONDecodeError, ValueError) as exc:
            _log.error("stock.json is corrupt or invalid: %s", exc)
            # Back up the corrupt file so data is not lost.
            backup = self.stock_path + ".bak"
            try:
                os.replace(self.stock_path, backup)
                _log.warning("A backup has been created at %s", backup)
            except OSError:
                pass
            self._cache = {}
            self._save_to_disk()

    def _save_to_disk(self) -> None:
        """Saves stock atomically (temp file + rename)."""
        tmp_path = self.stock_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, self.stock_path)  # atomic on POSIX and Windows
        except OSError as exc:
            _log.error("Could not save stock.json: %s", exc)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    # ------------------------------------------------------------------
    # Public read API (all async, all lock-protected)
    # ------------------------------------------------------------------

    def get_categories(self) -> List[str]:
        """Returns the list of existing categories (read-only, no lock needed)."""
        return list(self._cache.keys())

    async def get_stock_info(self) -> List[Tuple[str, int]]:
        """Returns a list of (category, available_amount) tuples."""
        async with self._lock:
            return [(cat, len(items)) for cat, items in self._cache.items()]

    async def get_total(self) -> int:
        """Total products in stock (sum of all categories)."""
        async with self._lock:
            return sum(len(items) for items in self._cache.values())

    async def get_category_count(self, category: str) -> int:
        """Available amount of a specific category."""
        async with self._lock:
            return len(self._cache.get(category, []))

    async def category_exists(self, category: str) -> bool:
        """Returns True if the category exists (even with 0 items)."""
        async with self._lock:
            return category in self._cache

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    async def pop_item(self, category: str) -> Optional[str]:
        """
        Removes (and returns) the first item of the category.

        Returns None if the category does not exist or is empty.
        The file is saved immediately so the change is never lost.
        """
        async with self._lock:
            items = self._cache.get(category)
            if not items:
                return None
            item = items.pop(0)
            self._save_to_disk()
            _log.debug("Item popped from '%s'. %d left.", category, len(items))
            return item

    async def restore_item(self, category: str, item: str) -> None:
        """
        Re-inserts an item at the beginning of a category.

        Used when a DM fails and the item must be returned to the stock so
        neither the user nor the item are lost.
        """
        async with self._lock:
            self._cache.setdefault(category, []).insert(0, item)
            self._save_to_disk()
            _log.debug("Item restored to '%s'. Total: %d.", category, len(self._cache[category]))

    async def add_item(self, category: str, item: str) -> int:
        """
        Adds a single item to a category. Creates the category if it does
        not exist (expandable stock).

        Returns the new total count for that category.
        """
        item = str(item)
        async with self._lock:
            self._cache.setdefault(category, []).append(item)
            self._save_to_disk()
            count = len(self._cache[category])
            _log.info("Item added to '%s'. Total now: %d.", category, count)
            return count

    async def add_items_bulk(self, category: str, items: List[str]) -> int:
        """
        Adds multiple items to a category. Creates the category if needed.

        Returns the new total count for that category.
        """
        clean_items = [str(i).strip() for i in items if str(i).strip()]
        if not clean_items:
            async with self._lock:
                return len(self._cache.get(category, []))

        async with self._lock:
            self._cache.setdefault(category, []).extend(clean_items)
            self._save_to_disk()
            count = len(self._cache[category])
            _log.info("%d items added to '%s'. Total now: %d.", len(clean_items), category, count)
            return count

    async def create_category(self, category: str) -> bool:
        """
        Creates a new empty category. Returns True if created, False if it
        already existed.
        """
        async with self._lock:
            if category in self._cache:
                return False
            self._cache[category] = []
            self._save_to_disk()
            _log.info("New empty category created: '%s'.", category)
            return True

    async def delete_category(self, category: str) -> bool:
        """
        Removes a category entirely (along with all its items).
        Returns True if deleted, False if the category did not exist.
        """
        async with self._lock:
            if category not in self._cache:
                return False
            del self._cache[category]
            self._save_to_disk()
            _log.info("Category '%s' deleted.", category)
            return True

    async def clear_category(self, category: str) -> int:
        """
        Removes all items in a category but keeps the category itself.
        Returns the number of items removed (0 if the category does not exist).
        """
        async with self._lock:
            if category not in self._cache:
                return 0
            removed = len(self._cache[category])
            self._cache[category] = []
            self._save_to_disk()
            _log.info("Cleared %d items from '%s'.", removed, category)
            return removed

    async def reload(self) -> None:
        """Reloads stock from disk (useful if manually edited)."""
        async with self._lock:
            self._load_from_disk()
            _log.info("Stock reloaded from disk.")
