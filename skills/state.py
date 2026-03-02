"""CLU Skills State Store — persistent enable/disable and runtime toggles.

Stores user preferences for the skills system in ~/.clu/skills-state.json.
All skills are enabled by default; only explicitly disabled names are stored.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = os.path.expanduser("~/.clu/skills-state.json")


class SkillStateStore:
    """Persistent store for skill enable/disable state and runtime toggles.

    Thread-safety: This class is not thread-safe. The web server uses a single
    module-level singleton accessed from async handlers — sufficient for CLU's
    single-process model.
    """

    def __init__(self, state_path: str | None = None) -> None:
        self._path = state_path or _DEFAULT_STATE_PATH
        self._loaded = False
        self._disabled: set[str] = set()
        self._auto_generate: bool | None = None  # None = use config default

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self, name: str) -> bool:
        """Return True if the skill is enabled (not explicitly disabled)."""
        self._ensure_loaded()
        return name not in self._disabled

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a skill by name and persist the change."""
        self._ensure_loaded()
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        self._save()

    def get_auto_generate(self) -> bool | None:
        """Return the stored auto-generate override, or None if not set."""
        self._ensure_loaded()
        return self._auto_generate

    def set_auto_generate(self, enabled: bool) -> None:
        """Override the auto-generate setting and persist."""
        self._ensure_loaded()
        self._auto_generate = enabled
        self._save()

    def disabled_names(self) -> set[str]:
        """Return the full set of explicitly disabled skill names."""
        self._ensure_loaded()
        return set(self._disabled)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._disabled = set(data.get("disabled", []))
            ag = data.get("auto_generate")
            if isinstance(ag, bool):
                self._auto_generate = ag
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Could not load skills state from %s: %s", self._path, e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            data: dict = {
                "disabled": sorted(self._disabled),
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if self._auto_generate is not None:
                data["auto_generate"] = self._auto_generate
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as e:
            logger.warning("Could not save skills state to %s: %s", self._path, e)
