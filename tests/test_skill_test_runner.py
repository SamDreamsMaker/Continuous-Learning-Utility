"""Tests for skills.test_runner — SkillTestRunner declarative test execution."""

import os
import tempfile
import textwrap

import pytest
import yaml

from skills.manifest import SkillManifest, SkillTestCase
from skills.test_runner import SkillTestRunner, SkillTestReport, SkillTestResult


# --- Helpers ---

def _make_tool_skill(td: str, tool_result: dict = None) -> SkillManifest:
    """Write a skill with a simple tool and return manifest."""
    result_repr = repr(tool_result or {"ok": True, "value": 42})
    skill_dir = os.path.join(td, "tool-skill")
    os.makedirs(os.path.join(skill_dir, "tools"), exist_ok=True)

    tool_code = textwrap.dedent(f"""\
        from tools.base import BaseTool
        class SimpleTool(BaseTool):
            @property
            def name(self): return "simple_tool"
            @property
            def description(self): return "A simple test tool"
            @property
            def parameters_schema(self): return {{"type": "object", "properties": {{}}}}
            def execute(self, args, project_path, sandbox, backup):
                return {result_repr}
    """)
    with open(os.path.join(skill_dir, "tools", "simple.py"), "w") as f:
        f.write(tool_code)

    data = {
        "name": "tool-skill",
        "version": "1.0.0",
        "tools": [{"module": "tools/simple.py", "class": "SimpleTool", "name": "simple_tool"}],
        "tests": [
            {
                "name": "tool_returns_ok",
                "type": "tool",
                "tool": "simple_tool",
                "input": {},
                "expect": {"has_key": "ok"},
            }
        ],
    }
    with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
        yaml.dump(data, f)

    return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")


def _make_check_skill(td: str, ok: bool = True) -> SkillManifest:
    """Write a skill with a simple check and return manifest."""
    skill_dir = os.path.join(td, "check-skill")
    os.makedirs(skill_dir, exist_ok=True)

    check_code = textwrap.dedent(f"""\
        from daemon.checks.base import CheckResult
        name = "simple_check"
        def run(project_path, **kwargs):
            return CheckResult(check_name=name, ok={ok}, summary="test check")
    """)
    with open(os.path.join(skill_dir, "simple_check.py"), "w") as f:
        f.write(check_code)

    data = {
        "name": "check-skill",
        "version": "1.0.0",
        "checks": [{"module": "simple_check.py", "name": "simple_check"}],
        "tests": [
            {
                "name": "check_is_ok",
                "type": "check",
                "check": "simple_check",
                "input": {},
                "expect": {"ok": True},
            }
        ],
    }
    with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
        yaml.dump(data, f)

    return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")


def _make_prompt_skill(td: str, content: str) -> SkillManifest:
    skill_dir = os.path.join(td, "prompt-skill")
    os.makedirs(skill_dir, exist_ok=True)

    with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
        f.write(content)

    data = {
        "name": "prompt-skill",
        "version": "1.0.0",
        "prompt": {"file": "prompt.md", "budget": 5000},
        "tests": [
            {
                "name": "prompt_has_content",
                "type": "prompt",
                "input": {},
                "expect": {"has_key": "content", "true_keys": ["content"]},
            }
        ],
    }
    with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
        yaml.dump(data, f)

    return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")


# --- Report structure tests ---

class TestSkillTestReport:

    def test_empty_report_has_zero_totals(self):
        report = SkillTestReport(skill_name="test")
        assert report.total == 0
        assert report.passed == 0
        assert report.failed == 0
        assert report.success is True

    def test_all_passing_report(self):
        results = [
            SkillTestResult("s", "t1", passed=True),
            SkillTestResult("s", "t2", passed=True),
        ]
        report = SkillTestReport(skill_name="s", results=results)
        assert report.passed == 2
        assert report.failed == 0
        assert report.success is True

    def test_mixed_report(self):
        results = [
            SkillTestResult("s", "t1", passed=True),
            SkillTestResult("s", "t2", passed=False, error="oops"),
        ]
        report = SkillTestReport(skill_name="s", results=results)
        assert report.passed == 1
        assert report.failed == 1
        assert report.success is False

    def test_to_dict_structure(self):
        report = SkillTestReport(skill_name="my-skill")
        d = report.to_dict()
        assert d["skill"] == "my-skill"
        assert "total" in d
        assert "passed" in d
        assert "results" in d


# --- Tool test execution ---

class TestToolTests:

    def test_tool_test_passes_with_correct_expect(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_tool_skill(td, tool_result={"ok": True, "value": 99})
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.total == 1
            assert report.passed == 1

    def test_tool_test_fails_wrong_key(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_tool_skill(td, tool_result={"ok": True})
            # Manually add a test with a wrong expectation
            manifest.tests[0].expect = {"has_key": "nonexistent_key"}
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.failed == 1
            assert "nonexistent_key" in report.results[0].error

    def test_tool_test_unknown_tool_fails(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_tool_skill(td)
            manifest.tests[0].tool = "nonexistent_tool"
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.failed == 1


# --- Check test execution ---

class TestCheckTests:

    def test_check_test_passes(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_check_skill(td, ok=True)
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.total == 1
            assert report.passed == 1

    def test_check_test_fails_wrong_ok(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_check_skill(td, ok=True)
            # Expect ok=False but check returns ok=True
            manifest.tests[0].expect = {"ok": False}
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.failed == 1

    def test_check_test_unknown_check_fails(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_check_skill(td)
            manifest.tests[0].check = "nonexistent_check"
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.failed == 1


# --- Prompt test execution ---

class TestPromptTests:

    def test_prompt_test_passes(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_prompt_skill(td, "Hello, this is skill guidance.")
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.passed == 1

    def test_prompt_test_contains_check(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_prompt_skill(td, "Unity guidance text.")
            manifest.tests[0].expect = {"contains": {"content": "Unity guidance"}}
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.passed == 1

    def test_prompt_test_fails_missing_substring(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _make_prompt_skill(td, "Short text.")
            manifest.tests[0].expect = {"contains": {"content": "this text does not exist"}}
            runner = SkillTestRunner()
            report = runner.run_skill(manifest)
            assert report.failed == 1


# --- No tests case ---

class TestNoTests:

    def test_skill_without_tests_empty_report(self):
        m = SkillManifest.from_yaml_dict(
            {"name": "no-tests", "version": "1.0.0"}, "/tmp", "bundled"
        )
        runner = SkillTestRunner()
        report = runner.run_skill(m)
        assert report.total == 0
        assert report.success is True


# --- Expectation engine ---

class TestExpectationEngine:

    def setup_method(self):
        self.runner = SkillTestRunner()
        self.check = self.runner._check_expectations

    def test_empty_expect_always_passes(self):
        passed, error = self.check({"any": "thing"}, {})
        assert passed is True

    def test_has_key_present(self):
        passed, _ = self.check({"foo": 1}, {"has_key": "foo"})
        assert passed is True

    def test_has_key_missing(self):
        passed, error = self.check({"bar": 1}, {"has_key": "foo"})
        assert passed is False
        assert "foo" in error

    def test_has_keys_all_present(self):
        passed, _ = self.check({"a": 1, "b": 2}, {"has_keys": ["a", "b"]})
        assert passed is True

    def test_has_keys_one_missing(self):
        passed, error = self.check({"a": 1}, {"has_keys": ["a", "b"]})
        assert passed is False

    def test_equals_match(self):
        passed, _ = self.check({"x": 42}, {"equals": {"x": 42}})
        assert passed is True

    def test_equals_mismatch(self):
        passed, error = self.check({"x": 42}, {"equals": {"x": 99}})
        assert passed is False
        assert "x" in error

    def test_contains_match(self):
        passed, _ = self.check({"msg": "hello world"}, {"contains": {"msg": "hello"}})
        assert passed is True

    def test_contains_mismatch(self):
        passed, error = self.check({"msg": "hello"}, {"contains": {"msg": "goodbye"}})
        assert passed is False

    def test_ok_true(self):
        passed, _ = self.check({"ok": True}, {"ok": True})
        assert passed is True

    def test_ok_false_mismatch(self):
        passed, error = self.check({"ok": False}, {"ok": True})
        assert passed is False

    def test_true_keys_truthy(self):
        passed, _ = self.check({"result": "something"}, {"true_keys": ["result"]})
        assert passed is True

    def test_true_keys_falsy(self):
        passed, error = self.check({"result": ""}, {"true_keys": ["result"]})
        assert passed is False

    def test_multiple_conditions_all_pass(self):
        actual = {"ok": True, "value": 42, "msg": "success"}
        expect = {
            "has_key": "ok",
            "ok": True,
            "equals": {"value": 42},
            "contains": {"msg": "succ"},
        }
        passed, _ = self.check(actual, expect)
        assert passed is True

    def test_multiple_conditions_one_fails(self):
        actual = {"ok": True, "value": 99}
        expect = {"ok": True, "equals": {"value": 42}}
        passed, error = self.check(actual, expect)
        assert passed is False


# --- run_skills (multi-skill) ---

class TestRunSkills:

    def test_run_skills_returns_one_report_per_skill(self):
        with tempfile.TemporaryDirectory() as td:
            m1 = _make_tool_skill(td)
            # Second skill in a different subdir
            td2 = os.path.join(td, "extra")
            os.makedirs(td2)
            m2 = _make_check_skill(td2)
            runner = SkillTestRunner()
            reports = runner.run_skills([m1, m2])
            assert len(reports) == 2

    def test_run_empty_list_returns_empty(self):
        runner = SkillTestRunner()
        assert runner.run_skills([]) == []
