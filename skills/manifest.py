"""Skill manifest — structured YAML manifest parsing and validation."""

import hashlib
import logging
import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from skills.exceptions import SkillIntegrityError, SkillLoadError, SkillRequirementError

logger = logging.getLogger(__name__)


# --- Data entries ---

@dataclass
class SkillToolEntry:
    """A tool contribution from a skill."""
    module: str
    class_name: str
    name: str


@dataclass
class SkillCheckEntry:
    """A heartbeat check contribution from a skill."""
    module: str
    name: str


@dataclass
class SkillTemplateEntry:
    """A task template contribution from a skill."""
    file: str
    name: str


@dataclass
class SkillPromptEntry:
    """Prompt injection configuration for a skill."""
    file: str
    budget: int = 3000
    keywords: list[str] = field(default_factory=list)


@dataclass
class SkillRequirements:
    """Pre-requisites that must be satisfied for a skill to load."""
    os: list[str] = field(default_factory=list)
    binaries: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class SkillTestCase:
    """A declarative test case defined in the manifest."""
    name: str
    type: str  # "tool" | "check" | "prompt"
    tool: str | None = None
    check: str | None = None
    input: dict = field(default_factory=dict)
    expect: dict = field(default_factory=dict)


# --- Main manifest ---

@dataclass
class SkillManifest:
    """Parsed and validated skill manifest (from skill.yaml)."""

    # Identity
    name: str
    version: str
    description: str
    author: str = ""
    tags: list[str] = field(default_factory=list)

    # Paths
    skill_dir: str = ""
    tier: str = "bundled"  # "bundled" | "user" | "project"

    # Integrity
    integrity: dict[str, str] = field(default_factory=dict)

    # Requirements
    requirements: SkillRequirements = field(default_factory=SkillRequirements)

    # Contributions
    tools: list[SkillToolEntry] = field(default_factory=list)
    checks: list[SkillCheckEntry] = field(default_factory=list)
    templates: list[SkillTemplateEntry] = field(default_factory=list)

    # Prompt
    prompt: SkillPromptEntry | None = None

    # Permissions
    roles: dict[str, list[str]] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)

    # Hooks
    hooks: dict[str, str] = field(default_factory=dict)

    # Tests
    tests: list[SkillTestCase] = field(default_factory=list)

    # Runtime state
    load_error: str | None = None
    _prompt_cache: str | None = field(default=None, repr=False)

    @classmethod
    def from_yaml_dict(cls, data: dict, skill_dir: str, tier: str = "bundled") -> "SkillManifest":
        """Parse a skill.yaml dict into a SkillManifest.

        Args:
            data: Parsed YAML dict.
            skill_dir: Absolute path to the skill directory.
            tier: Loading tier ("bundled", "user", or "project").

        Returns:
            SkillManifest instance.

        Raises:
            SkillLoadError: If required fields are missing.
        """
        if not isinstance(data, dict):
            raise SkillLoadError("Manifest must be a YAML mapping")

        name = data.get("name")
        version = data.get("version")
        description = data.get("description", "")

        if not name:
            raise SkillLoadError("Manifest missing required field: name")
        if not version:
            raise SkillLoadError("Manifest missing required field: version")

        # Parse requirements
        req_data = data.get("requires", {}) or {}
        requirements = SkillRequirements(
            os=req_data.get("os", []) or [],
            binaries=req_data.get("binaries", []) or [],
            files=req_data.get("files", []) or [],
            skills=req_data.get("skills", []) or [],
        )

        # Parse tool entries
        tools = []
        for t in data.get("tools", []) or []:
            tools.append(SkillToolEntry(
                module=t.get("module", ""),
                class_name=t.get("class", ""),
                name=t.get("name", ""),
            ))

        # Parse check entries
        checks = []
        for c in data.get("checks", []) or []:
            checks.append(SkillCheckEntry(
                module=c.get("module", ""),
                name=c.get("name", ""),
            ))

        # Parse template entries
        templates = []
        for tp in data.get("templates", []) or []:
            templates.append(SkillTemplateEntry(
                file=tp.get("file", ""),
                name=tp.get("name", ""),
            ))

        # Parse prompt entry
        prompt = None
        prompt_data = data.get("prompt")
        if prompt_data and isinstance(prompt_data, dict):
            prompt = SkillPromptEntry(
                file=prompt_data.get("file", "prompt.md"),
                budget=prompt_data.get("budget", 3000),
                keywords=prompt_data.get("keywords", []) or [],
            )

        # Parse roles
        roles = data.get("roles", {}) or {}

        # Parse tests
        tests = []
        for tc in data.get("tests", []) or []:
            tests.append(SkillTestCase(
                name=tc.get("name", ""),
                type=tc.get("type", "tool"),
                tool=tc.get("tool"),
                check=tc.get("check"),
                input=tc.get("input", {}),
                expect=tc.get("expect", {}),
            ))

        return cls(
            name=name,
            version=version,
            description=description,
            author=data.get("author", ""),
            tags=data.get("tags", []) or [],
            skill_dir=skill_dir,
            tier=tier,
            integrity=data.get("integrity", {}) or {},
            requirements=requirements,
            tools=tools,
            checks=checks,
            templates=templates,
            prompt=prompt,
            roles=roles,
            allowed_tools=data.get("allowed_tools", []) or [],
            hooks=data.get("hooks", {}) or {},
            tests=tests,
        )

    def check_requirements(self, project_path: str = "") -> tuple[bool, str]:
        """Check if this skill's requirements are met.

        Args:
            project_path: Path to the project root (for file checks).

        Returns:
            (satisfied, reason) — True if all requirements met.
        """
        req = self.requirements

        # OS check
        if req.os:
            current_os = platform.system().lower()
            os_map = {"windows": "win32", "linux": "linux", "darwin": "darwin"}
            current_mapped = os_map.get(current_os, current_os)
            if current_mapped not in req.os:
                return False, f"OS '{current_mapped}' not in {req.os}"

        # Binary check
        for binary in req.binaries:
            if shutil.which(binary) is None:
                return False, f"Required binary not found: {binary}"

        # File pattern check
        if req.files and project_path:
            import glob as glob_mod
            for pattern in req.files:
                matches = glob_mod.glob(
                    os.path.join(project_path, pattern), recursive=True
                )
                if not matches:
                    return False, f"Required file pattern not found: {pattern}"

        return True, "OK"

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """Verify SHA-256 integrity of all files declared in the manifest.

        Returns:
            (valid, errors) — True if all hashes match.
        """
        if not self.integrity:
            return True, []

        errors = []
        for rel_path, expected_hash in self.integrity.items():
            full_path = os.path.join(self.skill_dir, rel_path)

            if not os.path.isfile(full_path):
                errors.append(f"Missing file: {rel_path}")
                continue

            # Parse expected hash
            if expected_hash.startswith("sha256:"):
                expected = expected_hash[7:]
            else:
                expected = expected_hash

            # Compute actual hash
            actual = self._sha256_file(full_path)
            if actual != expected:
                errors.append(
                    f"Integrity mismatch for {rel_path}: "
                    f"expected {expected[:12]}..., got {actual[:12]}..."
                )

        return len(errors) == 0, errors

    def get_prompt_content(self) -> str:
        """Lazy-load and return the prompt content, respecting the budget.

        Returns:
            Prompt text (truncated to budget), or empty string if no prompt.
        """
        if self.prompt is None:
            return ""

        if self._prompt_cache is not None:
            return self._prompt_cache

        prompt_path = os.path.join(self.skill_dir, self.prompt.file)
        if not os.path.isfile(prompt_path):
            logger.warning("Prompt file not found: %s", prompt_path)
            self._prompt_cache = ""
            return ""

        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            logger.warning("Failed to read prompt %s: %s", prompt_path, e)
            self._prompt_cache = ""
            return ""

        # Budget enforcement
        if len(content) > self.prompt.budget:
            content = content[: self.prompt.budget]

        self._prompt_cache = content
        return content

    def is_prompt_relevant(self, task_text: str) -> bool:
        """Check if this skill's prompt is relevant to the given task.

        Uses deterministic keyword matching (case-insensitive).

        Args:
            task_text: The task description or user message.

        Returns:
            True if at least one keyword matches.
        """
        if self.prompt is None:
            return False

        if not self.prompt.keywords:
            # No keywords = always relevant
            return True

        task_lower = task_text.lower()
        return any(kw.lower() in task_lower for kw in self.prompt.keywords)

    def get_role_tools(self, role: str) -> list[str]:
        """Get the list of tool names available to a specific role.

        Args:
            role: Agent role (e.g., "coder", "reviewer", "tester").

        Returns:
            List of tool names. If no role mapping, returns all skill tool names.
        """
        if self.roles and role in self.roles:
            return self.roles[role]

        # Default: all tools from this skill
        return [t.name for t in self.tools]

    @staticmethod
    def _sha256_file(path: str) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
