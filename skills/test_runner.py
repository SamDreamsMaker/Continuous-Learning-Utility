"""Declarative skill test runner — executes skill.yaml test cases without an LLM."""

import importlib.util
import json
import logging
import os
import time
from dataclasses import dataclass, field

from skills.manifest import SkillManifest, SkillTestCase

logger = logging.getLogger(__name__)


@dataclass
class SkillTestResult:
    """Result of a single skill test case."""
    skill_name: str
    test_name: str
    passed: bool
    error: str | None = None
    actual: dict = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class SkillTestReport:
    """Aggregated report for all test cases in a skill."""
    skill_name: str
    results: list[SkillTestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        return {
            "skill": self.skill_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "success": self.success,
            "results": [
                {
                    "name": r.test_name,
                    "passed": r.passed,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                }
                for r in self.results
            ],
        }


class SkillTestRunner:
    """Runs declarative test cases defined in skill.yaml.

    Test case types:
    - ``tool``: Instantiates a skill tool and calls execute(); checks expected keys/values.
    - ``check``: Loads a skill check module and calls run(); checks expected fields.
    - ``prompt``: Loads prompt.md and checks expected substrings.

    No LLM is invoked — all tests run locally and deterministically.
    """

    def __init__(self, project_path: str = "/tmp"):
        self.project_path = project_path
        # Dummy sandbox and backup for tool tests
        self._sandbox = _NullSandbox()
        self._backup = _NullBackup()

    def run_skill(self, manifest: SkillManifest) -> SkillTestReport:
        """Run all test cases declared in a skill manifest.

        Args:
            manifest: Loaded SkillManifest with tests list.

        Returns:
            SkillTestReport with results for each test case.
        """
        report = SkillTestReport(skill_name=manifest.name)

        if not manifest.tests:
            logger.debug("Skill '%s' has no test cases", manifest.name)
            return report

        for tc in manifest.tests:
            result = self._run_one(manifest, tc)
            report.results.append(result)

        return report

    def run_skills(self, manifests: list[SkillManifest]) -> list[SkillTestReport]:
        """Run tests for all given skill manifests."""
        return [self.run_skill(m) for m in manifests]

    # ------------------------------------------------------------------
    # Internal test dispatch
    # ------------------------------------------------------------------

    def _run_one(self, manifest: SkillManifest, tc: SkillTestCase) -> SkillTestResult:
        """Run a single test case."""
        t0 = time.monotonic()
        try:
            if tc.type == "tool":
                actual = self._run_tool_test(manifest, tc)
            elif tc.type == "check":
                actual = self._run_check_test(manifest, tc)
            elif tc.type == "prompt":
                actual = self._run_prompt_test(manifest, tc)
            else:
                return SkillTestResult(
                    skill_name=manifest.name,
                    test_name=tc.name,
                    passed=False,
                    error=f"Unknown test type: {tc.type}",
                    duration_ms=(time.monotonic() - t0) * 1000,
                )

            passed, error = self._check_expectations(actual, tc.expect)
            return SkillTestResult(
                skill_name=manifest.name,
                test_name=tc.name,
                passed=passed,
                error=error,
                actual=actual,
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return SkillTestResult(
                skill_name=manifest.name,
                test_name=tc.name,
                passed=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=(time.monotonic() - t0) * 1000,
            )

    def _run_tool_test(self, manifest: SkillManifest, tc: SkillTestCase) -> dict:
        """Instantiate the tool and call execute()."""
        if not tc.tool:
            raise ValueError("Tool test case missing 'tool' field")

        # Find the tool entry
        entry = next((t for t in manifest.tools if t.name == tc.tool), None)
        if entry is None:
            raise ValueError(f"Tool '{tc.tool}' not found in skill '{manifest.name}'")

        module_path = os.path.join(manifest.skill_dir, entry.module)
        spec = importlib.util.spec_from_file_location(
            f"_skilltest_{manifest.name}_{tc.tool}", module_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cls = getattr(mod, entry.class_name)
        tool_instance = cls()

        return tool_instance.execute(
            tc.input, self.project_path, self._sandbox, self._backup
        )

    def _run_check_test(self, manifest: SkillManifest, tc: SkillTestCase) -> dict:
        """Load the check module and call run()."""
        if not tc.check:
            raise ValueError("Check test case missing 'check' field")

        entry = next((c for c in manifest.checks if c.name == tc.check), None)
        if entry is None:
            raise ValueError(f"Check '{tc.check}' not found in skill '{manifest.name}'")

        module_path = os.path.join(manifest.skill_dir, entry.module)
        spec = importlib.util.spec_from_file_location(
            f"_skilltest_check_{manifest.name}_{tc.check}", module_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        result = mod.run(self.project_path)
        return {
            "check_name": result.check_name,
            "ok": result.ok,
            "issue_count": result.issue_count,
            "summary": result.summary,
        }

    def _run_prompt_test(self, manifest: SkillManifest, tc: SkillTestCase) -> dict:
        """Load prompt content and return it for expectation checking."""
        content = manifest.get_prompt_content()
        return {"content": content, "length": len(content)}

    # ------------------------------------------------------------------
    # Expectation checking
    # ------------------------------------------------------------------

    def _check_expectations(self, actual: dict, expect: dict) -> tuple[bool, str | None]:
        """Check actual output against declared expectations.

        Supported expect keys:
        - ``has_key``:   key must exist in actual
        - ``has_keys``:  list of keys that must all exist
        - ``equals``:    {key: value} exact equality
        - ``contains``:  {key: substring} substring match (for strings)
        - ``ok``:        actual["ok"] must equal this bool
        - ``true_keys``: list of keys whose values must be truthy
        """
        if not expect:
            return True, None

        errors: list[str] = []

        # has_key (single key)
        if "has_key" in expect:
            key = expect["has_key"]
            if key not in actual:
                errors.append(f"Expected key '{key}' not in result. Got: {list(actual.keys())}")

        # has_keys (list of keys)
        if "has_keys" in expect:
            for key in expect["has_keys"]:
                if key not in actual:
                    errors.append(f"Expected key '{key}' not in result")

        # equals — exact values
        if "equals" in expect:
            for key, expected_val in expect["equals"].items():
                if key not in actual:
                    errors.append(f"Expected key '{key}' not present")
                elif actual[key] != expected_val:
                    errors.append(
                        f"Key '{key}': expected {expected_val!r}, got {actual[key]!r}"
                    )

        # contains — substring in string values
        if "contains" in expect:
            for key, substring in expect["contains"].items():
                if key not in actual:
                    errors.append(f"Expected key '{key}' not present")
                elif substring not in str(actual[key]):
                    errors.append(
                        f"Key '{key}': expected to contain {substring!r}, got {actual[key]!r}"
                    )

        # ok — shorthand for actual["ok"] == bool
        if "ok" in expect:
            if actual.get("ok") != expect["ok"]:
                errors.append(f"Expected ok={expect['ok']}, got ok={actual.get('ok')}")

        # true_keys — value must be truthy
        if "true_keys" in expect:
            for key in expect["true_keys"]:
                if not actual.get(key):
                    errors.append(f"Expected '{key}' to be truthy, got {actual.get(key)!r}")

        if errors:
            return False, "; ".join(errors)
        return True, None


# ------------------------------------------------------------------
# Null stubs (for tool test isolation)
# ------------------------------------------------------------------

class _NullSandbox:
    """No-op sandbox for tool test execution."""
    def validate(self, path: str) -> str:
        return path

    def is_allowed(self, path: str) -> bool:
        return True


class _NullBackup:
    """No-op backup manager for tool test execution."""
    @property
    def modified_files(self):
        return []

    def backup(self, path: str) -> str | None:
        return None
