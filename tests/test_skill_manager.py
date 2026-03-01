"""Tests for skills.manager — SkillManager tool registration, prompt injection, summary."""

import os
import sys
import tempfile
import textwrap

import pytest
import yaml

from skills.manifest import SkillManifest
from skills.manager import SkillManager


# --- Fixtures ---

def _make_manifest(name="test-skill", version="1.0.0", skill_dir="/tmp", **kwargs) -> SkillManifest:
    data = {"name": name, "version": version}
    data.update(kwargs)
    return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")


# --- Basic properties ---

class TestSkillManagerProperties:

    def test_empty_manager_has_zero_skills(self):
        mgr = SkillManager.empty()
        assert mgr.skill_count == 0
        assert mgr.skills == []

    def test_manager_has_correct_count(self):
        manifests = [_make_manifest("a"), _make_manifest("b"), _make_manifest("c")]
        mgr = SkillManager(manifests)
        assert mgr.skill_count == 3

    def test_get_skill_by_name(self):
        m = _make_manifest("my-skill")
        mgr = SkillManager([m])
        assert mgr.get_skill("my-skill") is m

    def test_get_unknown_skill_returns_none(self):
        mgr = SkillManager.empty()
        assert mgr.get_skill("nonexistent") is None

    def test_skills_property_returns_copy(self):
        m = _make_manifest("s")
        mgr = SkillManager([m])
        lst = mgr.skills
        lst.append(_make_manifest("extra"))
        assert mgr.skill_count == 1  # original unchanged

    def test_from_loader_calls_discover(self):
        """SkillManager.from_loader() should call loader.discover()."""
        class FakeLoader:
            def discover(self):
                return [_make_manifest("discovered")]

        mgr = SkillManager.from_loader(FakeLoader())
        assert mgr.skill_count == 1
        assert mgr.get_skill("discovered") is not None


# --- Tool registration ---

class TestToolRegistration:

    def _make_tool_skill(self, td: str) -> SkillManifest:
        """Build a skill with a real tool module in a temp directory."""
        skill_dir = os.path.join(td, "my-tool-skill")
        os.makedirs(skill_dir, exist_ok=True)

        # Write a simple BaseTool subclass
        tool_code = textwrap.dedent("""\
            from tools.base import BaseTool

            class DummyTool(BaseTool):
                @property
                def name(self): return "dummy_tool"
                @property
                def description(self): return "A dummy tool from a skill."
                @property
                def parameters_schema(self): return {"type": "object", "properties": {}}
                def execute(self, args, project_path, sandbox, backup):
                    return {"ok": True}
        """)
        os.makedirs(os.path.join(skill_dir, "tools"), exist_ok=True)
        with open(os.path.join(skill_dir, "tools", "dummy.py"), "w") as f:
            f.write(tool_code)

        data = {
            "name": "my-tool-skill",
            "version": "1.0.0",
            "tools": [{"module": "tools/dummy.py", "class": "DummyTool", "name": "dummy_tool"}],
        }
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            yaml.dump(data, f)

        return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

    def test_register_tools_empty_skill_returns_zero(self):
        from tools.registry import ToolRegistry
        mgr = SkillManager.empty()
        reg = ToolRegistry()
        count = mgr.register_tools(reg)
        assert count == 0

    def test_register_tool_from_skill(self):
        from tools.registry import ToolRegistry
        with tempfile.TemporaryDirectory() as td:
            m = self._make_tool_skill(td)
            mgr = SkillManager([m])
            reg = ToolRegistry()
            count = mgr.register_tools(reg, role="coder")
            assert count == 1
            tool = reg.get("dummy_tool")
            assert tool is not None
            assert tool.name == "dummy_tool"

    def test_register_tools_role_filtering(self):
        """Reviewer role: skill's roles.reviewer=[] → no tools registered."""
        from tools.registry import ToolRegistry
        with tempfile.TemporaryDirectory() as td:
            m = self._make_tool_skill(td)
            # Override roles so reviewer gets nothing
            m.roles = {"coder": ["dummy_tool"], "reviewer": []}
            mgr = SkillManager([m])
            reg = ToolRegistry()
            count = mgr.register_tools(reg, role="reviewer")
            assert count == 0

    def test_register_tool_missing_module_skipped(self):
        from tools.registry import ToolRegistry
        data = {
            "name": "bad-skill",
            "version": "1.0.0",
            "tools": [{"module": "nonexistent.py", "class": "Foo", "name": "foo"}],
        }
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        mgr = SkillManager([m])
        reg = ToolRegistry()
        # Should not raise — just log warning and skip
        count = mgr.register_tools(reg)
        assert count == 0

    def test_register_tool_not_basetool_skipped(self):
        from tools.registry import ToolRegistry
        with tempfile.TemporaryDirectory() as td:
            skill_dir = os.path.join(td, "notool")
            os.makedirs(skill_dir)
            # Write a class that does NOT extend BaseTool
            with open(os.path.join(skill_dir, "bad_tool.py"), "w") as f:
                f.write("class NotATool:\n    name = 'bad'\n")

            data = {
                "name": "notool",
                "version": "1.0.0",
                "tools": [{"module": "bad_tool.py", "class": "NotATool", "name": "bad"}],
            }
            m = SkillManifest.from_yaml_dict(data, skill_dir, "bundled")
            mgr = SkillManager([m])
            reg = ToolRegistry()
            count = mgr.register_tools(reg)
            assert count == 0


# --- Prompt injection ---

class TestPromptInjection:

    def _make_prompt_manifest(self, td, name, keywords, content, budget=5000):
        skill_dir = os.path.join(td, name)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
            f.write(content)
        data = {
            "name": name,
            "version": "1.0.0",
            "prompt": {"file": "prompt.md", "budget": budget, "keywords": keywords},
        }
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            yaml.dump(data, f)
        return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

    def test_no_relevant_skills_returns_empty(self):
        mgr = SkillManager.empty()
        result = mgr.get_prompt_injections("optimize Python database queries")
        assert result == ""

    def test_matching_skill_prompt_injected(self):
        with tempfile.TemporaryDirectory() as td:
            m = self._make_prompt_manifest(td, "unity-skill", ["unity"], "Unity tips here.")
            mgr = SkillManager([m])
            result = mgr.get_prompt_injections("Fix Unity compile error")
            assert "Unity tips here." in result
            assert "unity-skill" in result

    def test_non_matching_skill_not_injected(self):
        with tempfile.TemporaryDirectory() as td:
            m = self._make_prompt_manifest(td, "unity-skill", ["unity"], "Unity tips here.")
            mgr = SkillManager([m])
            result = mgr.get_prompt_injections("Optimize Python database")
            assert result == ""

    def test_global_budget_respected(self):
        with tempfile.TemporaryDirectory() as td:
            m1 = self._make_prompt_manifest(td, "skill-a", [], "A" * 4000, budget=4000)
            m2 = self._make_prompt_manifest(td, "skill-b", [], "B" * 4000, budget=4000)
            mgr = SkillManager([m1, m2])
            result = mgr.get_prompt_injections("anything", budget_chars=5000)
            # Only first skill fits within 5000
            assert "A" in result
            assert len(result) <= 5200  # budget + header overhead

    def test_multiple_matching_skills_all_injected(self):
        with tempfile.TemporaryDirectory() as td:
            m1 = self._make_prompt_manifest(td, "skill-a", ["python"], "Python tip A", budget=200)
            m2 = self._make_prompt_manifest(td, "skill-b", ["python"], "Python tip B", budget=200)
            mgr = SkillManager([m1, m2])
            result = mgr.get_prompt_injections("refactor Python code", budget_chars=10000)
            assert "Python tip A" in result
            assert "Python tip B" in result

    def test_skill_with_no_keywords_always_injected(self):
        with tempfile.TemporaryDirectory() as td:
            m = self._make_prompt_manifest(td, "global-skill", [], "Global guidance.")
            mgr = SkillManager([m])
            result = mgr.get_prompt_injections("unrelated task text")
            assert "Global guidance." in result

    def test_prompt_output_has_section_header(self):
        with tempfile.TemporaryDirectory() as td:
            m = self._make_prompt_manifest(td, "my-skill", [], "content here")
            mgr = SkillManager([m])
            result = mgr.get_prompt_injections("anything")
            assert result.startswith("## Skill Context")


# --- Summary / dashboard ---

class TestSummary:

    def test_summary_structure(self):
        m = _make_manifest("my-skill", description="A test skill", version="1.2.3")
        mgr = SkillManager([m])
        items = mgr.summary()
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "my-skill"
        assert item["version"] == "1.2.3"
        assert item["description"] == "A test skill"
        assert item["tier"] == "bundled"
        assert "tools" in item
        assert "checks" in item
        assert "has_prompt" in item

    def test_summary_empty_manager(self):
        mgr = SkillManager.empty()
        assert mgr.summary() == []


# --- runner.py integration smoke test ---

class TestRunnerIntegration:

    def test_runner_accepts_skill_manager(self):
        """AgentRunner should accept a skill_manager kwarg without error."""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock
        from orchestrator.runner import AgentRunner
        from orchestrator.config import AgentConfig

        config = AgentConfig()
        provider = MagicMock()
        provider.chat_completion = MagicMock(return_value=MagicMock(
            content="done", tool_calls=[], prompt_tokens=10, completion_tokens=5
        ))

        mgr = SkillManager.empty()
        runner = AgentRunner(
            config=config,
            provider=provider,
            project_path="/tmp",
            skill_manager=mgr,
        )
        assert runner.skill_manager is mgr

    def test_runner_default_skill_manager_is_empty(self):
        """Without skill_manager kwarg, runner should use empty SkillManager."""
        from unittest.mock import MagicMock
        from orchestrator.runner import AgentRunner
        from orchestrator.config import AgentConfig

        config = AgentConfig()
        provider = MagicMock()
        runner = AgentRunner(config=config, provider=provider, project_path="/tmp")
        assert runner.skill_manager.skill_count == 0

    def test_build_system_prompt_for_task_includes_skill_context(self):
        """_build_system_prompt_for_task should append skill prompt when relevant."""
        from unittest.mock import MagicMock
        from orchestrator.runner import AgentRunner
        from orchestrator.config import AgentConfig

        with tempfile.TemporaryDirectory() as td:
            skill_dir = os.path.join(td, "relevant-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
                f.write("Special guidance for python tasks.")
            data = {
                "name": "relevant-skill",
                "version": "1.0.0",
                "prompt": {"file": "prompt.md", "budget": 1000, "keywords": ["python"]},
            }
            with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
                yaml.dump(data, f)
            m = SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

            mgr = SkillManager([m])
            config = AgentConfig()
            provider = MagicMock()
            runner = AgentRunner(config=config, provider=provider,
                                 project_path="/tmp", skill_manager=mgr)

            prompt = runner._build_system_prompt_for_task("Refactor python code")
            assert "Special guidance for python tasks." in prompt

    def test_build_system_prompt_for_task_no_injection_when_irrelevant(self):
        """_build_system_prompt_for_task should not append when no keywords match."""
        from unittest.mock import MagicMock
        from orchestrator.runner import AgentRunner
        from orchestrator.config import AgentConfig

        with tempfile.TemporaryDirectory() as td:
            skill_dir = os.path.join(td, "unity-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
                f.write("Unity specific content.")
            data = {
                "name": "unity-skill",
                "version": "1.0.0",
                "prompt": {"file": "prompt.md", "budget": 1000, "keywords": ["unity", "csharp"]},
            }
            with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
                yaml.dump(data, f)
            m = SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

            mgr = SkillManager([m])
            config = AgentConfig()
            provider = MagicMock()
            runner = AgentRunner(config=config, provider=provider,
                                 project_path="/tmp", skill_manager=mgr)

            prompt = runner._build_system_prompt_for_task("Optimize Python code")
            assert "Unity specific content." not in prompt
