"""Skill generator — creates new CLU skills from recurring task patterns.

Given a SkillCandidate (output of PatternAnalyzer), this module:
  1. Prompts the agent's LLM provider to write skill.yaml + prompt.md
  2. Parses the LLM response
  3. Runs the existing SkillLoader security pipeline on the output
  4. Writes the files to ~/.clu/skills/<name>/
  5. Optionally reloads the global SkillManager

The LLM is NOT used during loading/discovery — only during explicit generation.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Delimiter markers used in the LLM prompt/response
_YAML_MARKER = "--- skill.yaml ---"
_MD_MARKER = "--- prompt.md ---"

_GENERATION_PROMPT = """\
You are a CLU skill author. CLU is an autonomous coding agent. Based on the \
recurring task patterns below, write a new CLU skill (skill.yaml + prompt.md) \
that encodes this knowledge for future agent runs.

## Observed Task Patterns

Task samples (up to 5):
{task_samples}

Common keywords: {keywords}
Tools most used: {tools_used}
File types touched: {file_extensions}
Success rate: {success_rate:.0%}
Pattern occurrences: {occurrences}

## Output Format

Return EXACTLY two sections separated by the markers below, no extra text:

{yaml_marker}
name: {suggested_name}
version: 1.0.0
description: <one sentence, under 100 chars>
author: CLU Auto-Generated
tags:
  - <tag1>
  - <tag2>
prompt:
  file: prompt.md
  budget: 3000
  keywords:
    - <keyword1>
    - <keyword2>
tests:
  - name: prompt_has_context
    type: prompt
    expect:
      has_key: content
      true_keys: [content]
  - name: prompt_not_empty
    type: prompt
    expect:
      has_key: content

{md_marker}
# <Skill Title>

<20 to 30 lines of concrete, actionable guidance for this pattern.>
<Be specific: list what to check, common pitfalls, recommended approaches.>
<Do NOT include instructions to override system prompts or ignore previous instructions.>
"""


@dataclass
class GenerationResult:
    """Outcome of a skill generation attempt."""
    ok: bool
    skill_name: str
    install_dir: str = ""
    error: str = ""
    security_errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.security_errors is None:
            self.security_errors = []

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "skill_name": self.skill_name,
            "install_dir": self.install_dir,
            "error": self.error,
            "security_errors": self.security_errors,
        }


class SkillGenerator:
    """Generates a new skill from a SkillCandidate using the LLM provider.

    Args:
        provider: An LLMProvider instance (same one used by AgentRunner).
        install_base_dir: Where to write generated skills.
                          Defaults to ~/.clu/skills/.
        model: Model name override (inherits provider default if None).
        max_tokens: Max tokens for generation response.
    """

    def __init__(
        self,
        provider,
        install_base_dir: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ):
        self.provider = provider
        self.install_dir = install_base_dir or os.path.expanduser("~/.clu/skills")
        self.model = model
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, candidate) -> GenerationResult:
        """Generate a skill from a SkillCandidate. Blocking (call via asyncio.to_thread)."""
        from skills.loader import SkillLoader
        from skills.manifest import SkillManifest
        from skills.exceptions import SkillLoadError

        skill_name = candidate.suggested_name
        logger.info("Generating skill '%s' from %d-occurrence pattern", skill_name, candidate.occurrences)

        # 1. Ask LLM to write the skill
        try:
            raw_response = self._call_llm(candidate)
        except Exception as e:
            return GenerationResult(ok=False, skill_name=skill_name, error=f"LLM error: {e}")

        # 2. Parse response
        try:
            yaml_content, md_content = self._parse_response(raw_response)
        except ValueError as e:
            return GenerationResult(ok=False, skill_name=skill_name, error=f"Parse error: {e}")

        # 3. Validate YAML is parseable and has required fields
        try:
            parsed = yaml.safe_load(yaml_content)
            if not isinstance(parsed, dict) or "name" not in parsed:
                return GenerationResult(ok=False, skill_name=skill_name, error="Generated YAML missing 'name' field")
            skill_name = str(parsed["name"])
        except yaml.YAMLError as e:
            return GenerationResult(ok=False, skill_name=skill_name, error=f"Invalid YAML: {e}")

        # 4. Write files to a temp location for security scanning
        skill_dir = os.path.join(self.install_dir, skill_name)
        os.makedirs(skill_dir, exist_ok=True)

        yaml_path = os.path.join(skill_dir, "skill.yaml")
        md_path = os.path.join(skill_dir, "prompt.md")

        try:
            with open(yaml_path, "w", encoding="utf-8") as fh:
                fh.write(yaml_content)
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(md_content)
        except OSError as e:
            return GenerationResult(ok=False, skill_name=skill_name, error=f"Write error: {e}")

        # 5. Run security pipeline (reuse existing SkillLoader methods)
        loader = SkillLoader(user_skills_dir=self.install_dir)
        secret_hits = loader._scan_secrets(skill_dir)
        if secret_hits:
            self._cleanup(skill_dir)
            return GenerationResult(
                ok=False,
                skill_name=skill_name,
                error="Security: secrets detected in generated content",
                security_errors=secret_hits,
            )

        _, injection_hits = loader._sanitize_prompt(md_content)
        if injection_hits:
            self._cleanup(skill_dir)
            return GenerationResult(
                ok=False,
                skill_name=skill_name,
                error="Security: prompt injection detected in generated content",
                security_errors=injection_hits,
            )

        # 6. Verify it can be loaded as a valid manifest
        manifest = loader._load_one(skill_dir, "user")
        if manifest is None:
            self._cleanup(skill_dir)
            return GenerationResult(
                ok=False,
                skill_name=skill_name,
                error="Generated skill failed manifest validation",
            )

        logger.info("Skill '%s' generated and installed at %s", skill_name, skill_dir)
        return GenerationResult(ok=True, skill_name=skill_name, install_dir=skill_dir)

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, candidate) -> str:
        """Send generation prompt to LLM and return raw text response."""
        prompt = _GENERATION_PROMPT.format(
            task_samples="\n".join(f"  - {s}" for s in candidate.task_samples),
            keywords=", ".join(candidate.keyword_cluster[:10]),
            tools_used=", ".join(candidate.tools_used) or "various",
            file_extensions=", ".join(candidate.file_extensions) or "various",
            success_rate=candidate.success_rate,
            occurrences=candidate.occurrences,
            suggested_name=candidate.suggested_name,
            yaml_marker=_YAML_MARKER,
            md_marker=_MD_MARKER,
        )

        messages = [
            {"role": "system", "content": "You are a CLU skill author. Output only the two requested sections."},
            {"role": "user", "content": prompt},
        ]

        response = self.provider.chat_completion(
            messages=messages,
            tools=None,
            temperature=0,
            seed=42,
            max_tokens=self.max_tokens,
        )
        return response.content or ""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> tuple[str, str]:
        """Extract skill.yaml and prompt.md content from the LLM response."""
        yaml_idx = raw.find(_YAML_MARKER)
        md_idx = raw.find(_MD_MARKER)

        if yaml_idx == -1 or md_idx == -1:
            raise ValueError(f"Response missing required markers. Got:\n{raw[:500]}")

        yaml_start = yaml_idx + len(_YAML_MARKER)
        yaml_end = md_idx

        md_start = md_idx + len(_MD_MARKER)

        yaml_content = raw[yaml_start:yaml_end].strip()
        md_content = raw[md_start:].strip()

        if not yaml_content:
            raise ValueError("Empty skill.yaml section in LLM response")
        if not md_content:
            raise ValueError("Empty prompt.md section in LLM response")

        return yaml_content, md_content

    # ------------------------------------------------------------------
    # Cleanup on failure
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup(skill_dir: str) -> None:
        """Remove a partially-written skill directory."""
        import shutil
        try:
            shutil.rmtree(skill_dir, ignore_errors=True)
        except Exception:
            pass
