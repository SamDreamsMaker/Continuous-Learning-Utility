"""Skill manager — orchestrates loaded skills: tools, checks, prompts."""

import importlib.util
import logging
import os

from skills.manifest import SkillManifest
from skills.state import SkillStateStore

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages a collection of loaded SkillManifest objects.

    Responsibilities:
    - Register skill-contributed tools into the ToolRegistry
    - Provide contextual prompt injections (keyword-matched, budget-limited)
    - Expose skill metadata for the dashboard and CLI

    Usage::

        loader = SkillLoader(project_skills_dir=".clu/skills")
        manager = SkillManager.from_loader(loader)
        manager.register_tools(registry, role="coder")
        prompt_suffix = manager.get_prompt_injections(task_text)
    """

    # Total chars budget for all injected skill prompts per run
    DEFAULT_PROMPT_BUDGET = 12_000

    def __init__(
        self,
        manifests: list[SkillManifest],
        state_store: SkillStateStore | None = None,
    ):
        self._manifests = manifests
        self._by_name: dict[str, SkillManifest] = {m.name: m for m in manifests}
        self._state = state_store

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_loader(
        cls,
        loader,
        state_store: SkillStateStore | None = None,
    ) -> "SkillManager":
        """Discover and load skills from the given SkillLoader."""
        manifests = loader.discover()
        return cls(manifests, state_store=state_store)

    @classmethod
    def empty(cls) -> "SkillManager":
        """Create an empty manager (no-op, useful as a default)."""
        return cls([])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def skills(self) -> list[SkillManifest]:
        """All loaded skill manifests (in dependency order)."""
        return list(self._manifests)

    @property
    def skill_count(self) -> int:
        return len(self._manifests)

    def get_skill(self, name: str) -> SkillManifest | None:
        """Lookup a skill by name."""
        return self._by_name.get(name)

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def register_tools(self, registry, role: str | None = None) -> int:
        """Register all skill-contributed tools into a ToolRegistry.

        Args:
            registry: ToolRegistry instance to register tools into.
            role: Current agent role (used for role-based filtering).

        Returns:
            Number of tools successfully registered.
        """
        from tools.base import BaseTool

        registered = 0
        effective_role = role or "coder"

        for manifest in self._manifests:
            if self._state and not self._state.is_enabled(manifest.name):
                continue
            available = set(manifest.get_role_tools(effective_role))
            for entry in manifest.tools:
                if entry.name not in available:
                    logger.debug(
                        "Skill '%s' tool '%s' not available for role '%s'",
                        manifest.name, entry.name, effective_role,
                    )
                    continue

                try:
                    tool_instance = self._load_tool_instance(manifest, entry)
                except Exception as e:
                    logger.warning(
                        "Skill '%s': failed to load tool '%s': %s",
                        manifest.name, entry.name, e,
                    )
                    continue

                if tool_instance is None:
                    continue
                if not isinstance(tool_instance, BaseTool):
                    logger.warning(
                        "Skill '%s' tool '%s' class '%s' does not extend BaseTool — skipped",
                        manifest.name, entry.name, entry.class_name,
                    )
                    continue

                registry.register(tool_instance)
                registered += 1
                logger.debug(
                    "Registered tool '%s' from skill '%s'", entry.name, manifest.name
                )

        return registered

    def _load_tool_instance(self, manifest: SkillManifest, entry):
        """Dynamically load a tool class from a skill module file."""
        module_path = os.path.join(manifest.skill_dir, entry.module)
        if not os.path.isfile(module_path):
            logger.warning("Tool module not found: %s", module_path)
            return None

        module_name = f"_skill_{manifest.name}_{entry.name}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            logger.warning("Cannot create module spec for: %s", module_path)
            return None

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cls = getattr(mod, entry.class_name, None)
        if cls is None:
            logger.warning(
                "Class '%s' not found in module '%s'", entry.class_name, module_path
            )
            return None

        return cls()

    # ------------------------------------------------------------------
    # Prompt injection (Phase 4 feature)
    # ------------------------------------------------------------------

    def get_prompt_injections(
        self,
        task_text: str,
        budget_chars: int = DEFAULT_PROMPT_BUDGET,
    ) -> str:
        """Build a prompt suffix from all relevant skill prompts.

        Selects skills whose keywords match the task (case-insensitive),
        appends each prompt in dependency order, and stops when the
        character budget is exhausted.

        Args:
            task_text: The task description or user message.
            budget_chars: Maximum total characters across all injected prompts.

        Returns:
            Formatted prompt string (empty string if nothing is relevant).
        """
        parts: list[str] = []
        used = 0

        for manifest in self._manifests:
            if self._state and not self._state.is_enabled(manifest.name):
                continue
            if not manifest.is_prompt_relevant(task_text):
                continue

            content = manifest.get_prompt_content()
            if not content:
                continue

            # Per-skill budget already enforced by manifest; enforce global here
            available = budget_chars - used
            if available <= 0:
                logger.debug("Global skill prompt budget exhausted after %d chars", used)
                break

            if len(content) > available:
                content = content[:available]

            parts.append(f"### [{manifest.name} v{manifest.version}]\n{content}")
            used += len(content)

        if not parts:
            return ""

        return "## Skill Context\n\n" + "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Dashboard / introspection
    # ------------------------------------------------------------------

    def summary(self) -> list[dict]:
        """Return a JSON-serializable summary of all loaded skills."""
        result = []
        for m in self._manifests:
            enabled = self._state.is_enabled(m.name) if self._state else True
            result.append({
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "tier": m.tier,
                "author": m.author,
                "tags": m.tags,
                "tools": [t.name for t in m.tools],
                "checks": [c.name for c in m.checks],
                "has_prompt": m.prompt is not None,
                "load_error": m.load_error,
                "enabled": enabled,
            })
        return result
