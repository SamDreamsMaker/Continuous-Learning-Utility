"""Skill loader — 4-tier discovery, validation, secret scanning, and dependency ordering."""

import logging
import os
import re
from collections import defaultdict, deque

import yaml

from skills.exceptions import SkillLoadError
from skills.manifest import SkillManifest

logger = logging.getLogger(__name__)

# Tier ordering (higher = higher priority for deduplication)
# project > user > registry > bundled
_TIER_PRIORITY = {"bundled": 0, "registry": 1, "user": 2, "project": 3}

# --- Security patterns ---

# Patterns that indicate a hardcoded secret in a skill file
_SECRET_PATTERNS: list[re.Pattern] = [
    # Generic key=value secrets
    re.compile(
        r"""(?ix)
        (api[_-]?key | secret[_-]?key | access[_-]?token | auth[_-]?token
         | password | passwd | credential | private[_-]?key)
        ['"]?\s*[:=]\s*['"]?[A-Za-z0-9+/._\-]{20,}
        """
    ),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),            # OpenAI key
    re.compile(r"ghp_[A-Za-z0-9]{36}"),             # GitHub personal token
    re.compile(r"ghs_[A-Za-z0-9]{36}"),             # GitHub server token
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),          # Google API key
    re.compile(r"AKIA[0-9A-Z]{16}"),                # AWS access key
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9\-._~+/]{40,}"),  # Bearer token
]

# Patterns that indicate a prompt injection attempt in prompt.md
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)ignore\s+(previous|all|above)\s+instructions?"),
    re.compile(r"(?i)forget\s+(everything|all|your\s+instructions?)"),
    re.compile(r"(?i)\byou\s+are\s+now\b"),
    re.compile(r"(?i)\bact\s+as\b"),
    re.compile(r"(?i)\bpretend\s+(to\s+be|you\s+are)\b"),
    re.compile(r"(?i)\byour\s+(new\s+)?role\s+is\b"),
    re.compile(r"(?i)\boverride\s+(system|instructions?|prompt)\b"),
    re.compile(r"(?i)\b(system\s+prompt|system\s+message)\s*[:=]"),
    re.compile(r"(?i)\bDAN\b"),                     # "Do Anything Now" jailbreak keyword
]

# File extensions to scan for secrets (text files only)
_SCANNABLE_EXTENSIONS = {".py", ".yaml", ".yml", ".md", ".txt", ".toml", ".json", ".sh"}


class SkillLoader:
    """Discovers and loads skills from 4 tiers: bundled → registry → user → project.

    Tier resolution (highest priority wins):
    - Bundled:  ``skills/bundled/`` (shipped with CLU)
    - Registry: ``~/.clu/registry-cache/`` (community skills, auto-synced)
    - User:     ``~/.clu/skills/`` (user global installs)
    - Project:  ``<project>/.clu/skills/`` (project-local overrides)

    When two tiers define the same skill name, the higher-priority tier wins.
    Load order respects declared skill dependencies (topological sort).
    """

    BUNDLED_DIR = os.path.join(os.path.dirname(__file__), "bundled")

    def __init__(
        self,
        user_skills_dir: str | None = None,
        project_skills_dir: str | None = None,
        registry_cache_dir: str | None = None,
    ):
        self.user_dir = user_skills_dir or os.path.expanduser("~/.clu/skills")
        self.project_dir = project_skills_dir  # None = not set
        from skills.registry import registry_cache_dir as _default_cache_dir
        self.registry_dir = registry_cache_dir or _default_cache_dir()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> list[SkillManifest]:
        """Discover all valid skills across all tiers.

        Returns:
            Ordered list of SkillManifest objects (dependency order, lowest-tier first).
            Skills that fail validation are logged and excluded.
        """
        raw: list[SkillManifest] = []

        # Load each tier (lowest priority first)
        raw.extend(self._load_tier(self.BUNDLED_DIR, "bundled"))
        raw.extend(self._load_tier(self.registry_dir, "registry"))
        raw.extend(self._load_tier(self.user_dir, "user"))
        if self.project_dir:
            raw.extend(self._load_tier(self.project_dir, "project"))

        # Deduplicate: higher tier wins
        deduplicated = self._deduplicate(raw)

        # Topological sort by dependency
        try:
            ordered = self._topological_sort(deduplicated)
        except SkillLoadError as e:
            logger.error("Dependency error in skills: %s", e)
            ordered = deduplicated  # fallback: unordered but don't crash

        logger.info("Skills loaded: %d", len(ordered))
        return ordered

    # ------------------------------------------------------------------
    # Tier loading
    # ------------------------------------------------------------------

    def _load_tier(self, base_dir: str, tier: str) -> list[SkillManifest]:
        """Load all skills from a directory."""
        if not os.path.isdir(base_dir):
            return []

        manifests = []
        for entry in sorted(os.scandir(base_dir), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            manifest = self._load_one(entry.path, tier)
            if manifest is not None:
                manifests.append(manifest)
        return manifests

    def _load_one(self, skill_dir: str, tier: str) -> SkillManifest | None:
        """Load and fully validate a single skill directory.

        Returns None (and logs) if any validation step fails.
        """
        yaml_path = os.path.join(skill_dir, "skill.yaml")
        if not os.path.isfile(yaml_path):
            return None

        # 1. Parse YAML
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.warning("Skipping skill %s — YAML parse error: %s", skill_dir, e)
            return None

        try:
            manifest = SkillManifest.from_yaml_dict(data, skill_dir, tier)
        except SkillLoadError as e:
            logger.warning("Skipping skill %s — manifest error: %s", skill_dir, e)
            return None

        # 2. Integrity verification
        valid, errors = manifest.verify_integrity()
        if not valid:
            logger.warning(
                "Skipping skill '%s' — integrity errors: %s",
                manifest.name, "; ".join(errors),
            )
            manifest.load_error = f"Integrity: {errors[0]}"
            return None

        # 3. Secret scanning
        secret_hits = self._scan_secrets(skill_dir)
        if secret_hits:
            logger.warning(
                "Skipping skill '%s' — secrets detected: %s",
                manifest.name, "; ".join(secret_hits),
            )
            manifest.load_error = f"Secrets: {secret_hits[0]}"
            return None

        # 4. Prompt sanitization
        if manifest.prompt:
            prompt_path = os.path.join(skill_dir, manifest.prompt.file)
            if os.path.isfile(prompt_path):
                try:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                    _, injection_hits = self._sanitize_prompt(prompt_content)
                    if injection_hits:
                        logger.warning(
                            "Skipping skill '%s' — prompt injection detected: %s",
                            manifest.name, "; ".join(injection_hits),
                        )
                        manifest.load_error = f"Injection: {injection_hits[0]}"
                        return None
                except OSError as e:
                    logger.warning("Cannot read prompt for '%s': %s", manifest.name, e)

        logger.debug("Loaded skill '%s' v%s [%s]", manifest.name, manifest.version, tier)
        return manifest

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    def _scan_secrets(self, skill_dir: str) -> list[str]:
        """Scan all text files in a skill directory for hardcoded secrets.

        Returns:
            List of human-readable hit descriptions (empty = clean).
        """
        hits = []
        for root, _dirs, files in os.walk(skill_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _SCANNABLE_EXTENSIONS:
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue

                rel = os.path.relpath(fpath, skill_dir)
                for pattern in _SECRET_PATTERNS:
                    match = pattern.search(content)
                    if match:
                        # Show only start of match to avoid leaking secrets in logs
                        snippet = match.group(0)[:40]
                        hits.append(f"{rel}: '{snippet}...'")
                        break  # one hit per file is enough

        return hits

    def _sanitize_prompt(self, content: str) -> tuple[str, list[str]]:
        """Check prompt content for injection patterns.

        Args:
            content: Raw prompt file content.

        Returns:
            (content, hits) — content unchanged; hits is a list of matches found.
        """
        hits = []
        for pattern in _INJECTION_PATTERNS:
            match = pattern.search(content)
            if match:
                hits.append(f"Pattern '{pattern.pattern[:40]}' matched: '{match.group(0)}'")
        return content, hits

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate(self, manifests: list[SkillManifest]) -> list[SkillManifest]:
        """Keep only the highest-priority tier version of each skill name."""
        seen: dict[str, SkillManifest] = {}
        for m in manifests:
            existing = seen.get(m.name)
            if existing is None:
                seen[m.name] = m
            else:
                if _TIER_PRIORITY[m.tier] > _TIER_PRIORITY[existing.tier]:
                    logger.debug(
                        "Skill '%s' overridden by %s tier (was %s)",
                        m.name, m.tier, existing.tier,
                    )
                    seen[m.name] = m
        # Preserve insertion order (bundled first, then overrides)
        return list(seen.values())

    # ------------------------------------------------------------------
    # Dependency ordering (Kahn's BFS topological sort)
    # ------------------------------------------------------------------

    def _topological_sort(self, manifests: list[SkillManifest]) -> list[SkillManifest]:
        """Sort manifests so that dependencies load before dependants.

        Args:
            manifests: Deduplicated list of manifests.

        Returns:
            Dependency-ordered list.

        Raises:
            SkillLoadError: On circular dependency.
        """
        name_to_manifest = {m.name: m for m in manifests}
        # in-degree and adjacency list
        in_degree: dict[str, int] = {m.name: 0 for m in manifests}
        dependants: dict[str, list[str]] = defaultdict(list)

        for m in manifests:
            for dep in m.requirements.skills:
                if dep not in name_to_manifest:
                    # Missing dependency — log and skip (don't block other skills)
                    logger.warning(
                        "Skill '%s' requires '%s' which is not loaded; skipping dependency",
                        m.name, dep,
                    )
                    continue
                dependants[dep].append(m.name)
                in_degree[m.name] += 1

        # BFS from zero-in-degree nodes
        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        ordered: list[SkillManifest] = []

        while queue:
            name = queue.popleft()
            ordered.append(name_to_manifest[name])
            for dependant in dependants[name]:
                in_degree[dependant] -= 1
                if in_degree[dependant] == 0:
                    queue.append(dependant)

        if len(ordered) != len(manifests):
            cycle_nodes = [n for n, deg in in_degree.items() if deg > 0]
            raise SkillLoadError(f"Circular skill dependency detected: {cycle_nodes}")

        return ordered
