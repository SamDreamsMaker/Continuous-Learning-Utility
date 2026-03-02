"""CLU Context Store — user-managed context items injected into every agent run.

Items are stored in {project_path}/.clu/user-context.json as a simple JSON list.
Each item has a name, content text, an enabled toggle, and an optional scope.
Active items are injected into the system prompt under ## User Context.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

VALID_SCOPES = ("always", "coder", "reviewer", "tester")


@dataclass
class ContextItem:
    id: str
    name: str
    content: str
    enabled: bool = True
    created_at: str = ""
    scope: str = "always"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ContextItem":
        scope = d.get("scope", "always")
        if scope not in VALID_SCOPES:
            scope = "always"
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            content=d.get("content", ""),
            enabled=bool(d.get("enabled", True)),
            created_at=d.get("created_at", ""),
            scope=scope,
        )


class ContextStore:
    """Persistent store for user-defined context items.

    Thread-safety: Not thread-safe. Sufficient for CLU's single-process
    async web server model (same pattern as SkillStateStore).
    """

    def __init__(self, project_path: str) -> None:
        self._path = os.path.join(project_path, ".clu", "user-context.json")
        self._loaded = False
        self._items: list[ContextItem] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_items(self) -> list[ContextItem]:
        """Return all context items (enabled and disabled)."""
        self._ensure_loaded()
        return list(self._items)

    def add_item(self, name: str, content: str, scope: str = "always") -> ContextItem:
        """Create a new context item and persist it."""
        self._ensure_loaded()
        if scope not in VALID_SCOPES:
            scope = "always"
        item = ContextItem(
            id=str(uuid.uuid4()),
            name=name.strip(),
            content=content,
            enabled=True,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            scope=scope,
        )
        self._items.append(item)
        self._save()
        return item

    def update_item(self, item_id: str, **kwargs) -> ContextItem | None:
        """Update fields on an existing item. Returns None if not found."""
        self._ensure_loaded()
        for item in self._items:
            if item.id == item_id:
                if "name" in kwargs:
                    item.name = str(kwargs["name"]).strip()
                if "content" in kwargs:
                    item.content = str(kwargs["content"])
                if "enabled" in kwargs:
                    item.enabled = bool(kwargs["enabled"])
                if "scope" in kwargs and kwargs["scope"] in VALID_SCOPES:
                    item.scope = kwargs["scope"]
                self._save()
                return item
        return None

    def delete_item(self, item_id: str) -> bool:
        """Delete an item by id. Returns True if deleted, False if not found."""
        self._ensure_loaded()
        before = len(self._items)
        self._items = [i for i in self._items if i.id != item_id]
        if len(self._items) < before:
            self._save()
            return True
        return False

    def get_item_by_name(self, name: str) -> ContextItem | None:
        """Find an item by name (case-insensitive). Returns first match."""
        self._ensure_loaded()
        name_lower = name.strip().lower()
        for item in self._items:
            if item.name.lower() == name_lower:
                return item
        return None

    def get_active_text(self, role: str | None = None) -> str:
        """Build the ## User Context block for system prompt injection.

        Items with scope='always' are always included.
        Items with a role scope are only included when role matches.
        Returns empty string when no active items exist.
        """
        self._ensure_loaded()
        active = [
            i for i in self._items
            if i.enabled and i.content.strip()
            and (i.scope == "always" or i.scope == role)
        ]
        if not active:
            return ""
        parts = [f"### {i.name}\n{i.content.strip()}" for i in active]
        return "## User Context\n\n" + "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._items = [ContextItem.from_dict(d) for d in data.get("items", [])]
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Could not load context store from %s: %s", self._path, e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            data = {
                "items": [i.to_dict() for i in self._items],
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as e:
            logger.warning("Could not save context store to %s: %s", self._path, e)
