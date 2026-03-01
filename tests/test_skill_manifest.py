"""Tests for skills.manifest — SkillManifest parsing, integrity, requirements, prompts."""

import hashlib
import os
import tempfile

import pytest

from skills.exceptions import SkillIntegrityError, SkillLoadError, SkillRequirementError
from skills.manifest import (
    SkillCheckEntry,
    SkillManifest,
    SkillPromptEntry,
    SkillRequirements,
    SkillTemplateEntry,
    SkillTestCase,
    SkillToolEntry,
)


# --- Fixtures ---

def _minimal_yaml():
    """Minimal valid skill manifest."""
    return {"name": "test-skill", "version": "1.0.0"}


def _full_yaml(skill_dir: str = "/tmp/skill"):
    """Complete skill manifest with all sections."""
    return {
        "name": "unity-support",
        "version": "2.1.0",
        "description": "Unity/C# development tools",
        "author": "CLU Team",
        "tags": ["unity", "csharp"],
        "integrity": {},
        "requires": {
            "os": ["win32", "linux", "darwin"],
            "binaries": ["python"],
            "files": [],
            "skills": [],
        },
        "tools": [
            {"module": "tools/validate.py", "class": "ValidateCSharpTool", "name": "validate_csharp"},
        ],
        "checks": [
            {"module": "checks/unity_compile.py", "name": "unity_compile"},
        ],
        "templates": [
            {"file": "templates/auto_fix.md", "name": "auto_fix_compile"},
        ],
        "prompt": {
            "file": "prompt.md",
            "budget": 500,
            "keywords": ["unity", "csharp", "monobehaviour"],
        },
        "roles": {
            "coder": ["validate_csharp"],
            "reviewer": [],
        },
        "allowed_tools": ["think", "read_file"],
        "hooks": {"on_activate": "tools/validate.py:on_activate"},
        "tests": [
            {
                "name": "tool_returns_result",
                "type": "tool",
                "tool": "validate_csharp",
                "input": {"code": "class T {}"},
                "expect": {"has_key": "valid"},
            },
        ],
    }


# --- Parse tests ---

class TestManifestParsing:

    def test_parse_minimal(self):
        m = SkillManifest.from_yaml_dict(_minimal_yaml(), "/tmp/skill", "bundled")
        assert m.name == "test-skill"
        assert m.version == "1.0.0"
        assert m.description == ""
        assert m.tools == []
        assert m.prompt is None
        assert m.tier == "bundled"

    def test_parse_full(self):
        m = SkillManifest.from_yaml_dict(_full_yaml(), "/tmp/skill", "project")
        assert m.name == "unity-support"
        assert m.version == "2.1.0"
        assert m.author == "CLU Team"
        assert m.tags == ["unity", "csharp"]
        assert m.tier == "project"
        assert len(m.tools) == 1
        assert m.tools[0].name == "validate_csharp"
        assert m.tools[0].class_name == "ValidateCSharpTool"
        assert len(m.checks) == 1
        assert m.checks[0].name == "unity_compile"
        assert len(m.templates) == 1
        assert m.templates[0].name == "auto_fix_compile"
        assert m.prompt is not None
        assert m.prompt.budget == 500
        assert m.prompt.keywords == ["unity", "csharp", "monobehaviour"]
        assert m.roles["coder"] == ["validate_csharp"]
        assert m.roles["reviewer"] == []
        assert m.allowed_tools == ["think", "read_file"]
        assert len(m.tests) == 1
        assert m.tests[0].name == "tool_returns_result"

    def test_parse_missing_name_raises(self):
        with pytest.raises(SkillLoadError, match="name"):
            SkillManifest.from_yaml_dict({"version": "1.0.0"}, "/tmp", "bundled")

    def test_parse_missing_version_raises(self):
        with pytest.raises(SkillLoadError, match="version"):
            SkillManifest.from_yaml_dict({"name": "test"}, "/tmp", "bundled")

    def test_parse_invalid_type_raises(self):
        with pytest.raises(SkillLoadError, match="mapping"):
            SkillManifest.from_yaml_dict("not a dict", "/tmp", "bundled")

    def test_parse_none_sections_default_to_empty(self):
        data = {"name": "test", "version": "1.0.0", "tools": None, "checks": None, "tags": None}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.tools == []
        assert m.checks == []
        assert m.tags == []


# --- Integrity tests ---

class TestIntegrity:

    def test_verify_no_integrity_section_passes(self):
        m = SkillManifest.from_yaml_dict(_minimal_yaml(), "/tmp", "bundled")
        valid, errors = m.verify_integrity()
        assert valid is True
        assert errors == []

    def test_verify_correct_hash(self):
        with tempfile.TemporaryDirectory() as td:
            # Write a file and compute its hash
            fpath = os.path.join(td, "prompt.md")
            content = b"Hello, skill!"
            with open(fpath, "wb") as f:
                f.write(content)
            expected = hashlib.sha256(content).hexdigest()

            data = _minimal_yaml()
            data["integrity"] = {"prompt.md": f"sha256:{expected}"}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            valid, errors = m.verify_integrity()
            assert valid is True
            assert errors == []

    def test_verify_tampered_hash(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "prompt.md")
            with open(fpath, "wb") as f:
                f.write(b"original content")

            data = _minimal_yaml()
            data["integrity"] = {"prompt.md": "sha256:0000000000000000000000000000000000000000000000000000000000000000"}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            valid, errors = m.verify_integrity()
            assert valid is False
            assert len(errors) == 1
            assert "mismatch" in errors[0].lower()

    def test_verify_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            data = _minimal_yaml()
            data["integrity"] = {"nonexistent.py": "sha256:abc"}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            valid, errors = m.verify_integrity()
            assert valid is False
            assert "Missing file" in errors[0]


# --- Requirements gating tests ---

class TestRequirements:

    def test_no_requirements_passes(self):
        m = SkillManifest.from_yaml_dict(_minimal_yaml(), "/tmp", "bundled")
        ok, reason = m.check_requirements()
        assert ok is True

    def test_os_requirement_current_passes(self):
        import platform as plat
        os_map = {"windows": "win32", "linux": "linux", "darwin": "darwin"}
        current = os_map.get(plat.system().lower(), plat.system().lower())
        data = _minimal_yaml()
        data["requires"] = {"os": [current]}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        ok, reason = m.check_requirements()
        assert ok is True

    def test_os_requirement_wrong_fails(self):
        data = _minimal_yaml()
        data["requires"] = {"os": ["fake_os_99"]}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        ok, reason = m.check_requirements()
        assert ok is False
        assert "OS" in reason

    def test_binary_requirement_python_passes(self):
        data = _minimal_yaml()
        data["requires"] = {"binaries": ["python"]}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        ok, reason = m.check_requirements()
        assert ok is True

    def test_binary_requirement_missing_fails(self):
        data = _minimal_yaml()
        data["requires"] = {"binaries": ["nonexistent_binary_xyz_999"]}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        ok, reason = m.check_requirements()
        assert ok is False
        assert "binary" in reason.lower()

    def test_file_requirement_matches(self):
        with tempfile.TemporaryDirectory() as td:
            # Create a matching file
            os.makedirs(os.path.join(td, "src"), exist_ok=True)
            with open(os.path.join(td, "src", "test.py"), "w") as f:
                f.write("pass")

            data = _minimal_yaml()
            data["requires"] = {"files": ["src/*.py"]}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")
            ok, reason = m.check_requirements(project_path=td)
            assert ok is True

    def test_file_requirement_missing_fails(self):
        with tempfile.TemporaryDirectory() as td:
            data = _minimal_yaml()
            data["requires"] = {"files": ["*.sln"]}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")
            ok, reason = m.check_requirements(project_path=td)
            assert ok is False
            assert "*.sln" in reason


# --- Keyword matching tests ---

class TestKeywordMatching:

    def test_relevant_when_keyword_matches(self):
        data = _full_yaml()
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.is_prompt_relevant("Fix the Unity compile error") is True

    def test_relevant_case_insensitive(self):
        data = _full_yaml()
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.is_prompt_relevant("Fix the CSHARP class") is True

    def test_not_relevant_when_no_match(self):
        data = _full_yaml()
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.is_prompt_relevant("Optimize Python database queries") is False

    def test_always_relevant_when_no_keywords(self):
        data = _minimal_yaml()
        data["prompt"] = {"file": "prompt.md", "budget": 1000, "keywords": []}
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.is_prompt_relevant("anything at all") is True

    def test_not_relevant_when_no_prompt(self):
        m = SkillManifest.from_yaml_dict(_minimal_yaml(), "/tmp", "bundled")
        assert m.is_prompt_relevant("unity csharp") is False


# --- Budget enforcement tests ---

class TestBudget:

    def test_prompt_loaded_within_budget(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "prompt.md")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("Short prompt")

            data = _minimal_yaml()
            data["prompt"] = {"file": "prompt.md", "budget": 1000}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            content = m.get_prompt_content()
            assert content == "Short prompt"

    def test_prompt_truncated_at_budget(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "prompt.md")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("A" * 5000)

            data = _minimal_yaml()
            data["prompt"] = {"file": "prompt.md", "budget": 100}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            content = m.get_prompt_content()
            assert len(content) == 100

    def test_prompt_cached_after_first_load(self):
        with tempfile.TemporaryDirectory() as td:
            fpath = os.path.join(td, "prompt.md")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("Hello")

            data = _minimal_yaml()
            data["prompt"] = {"file": "prompt.md", "budget": 1000}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")

            c1 = m.get_prompt_content()
            # Overwrite file — cache should still return old value
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("Changed")
            c2 = m.get_prompt_content()
            assert c1 == c2 == "Hello"

    def test_prompt_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            data = _minimal_yaml()
            data["prompt"] = {"file": "nonexistent.md", "budget": 1000}
            m = SkillManifest.from_yaml_dict(data, td, "bundled")
            assert m.get_prompt_content() == ""

    def test_no_prompt_returns_empty(self):
        m = SkillManifest.from_yaml_dict(_minimal_yaml(), "/tmp", "bundled")
        assert m.get_prompt_content() == ""


# --- Role tools tests ---

class TestRoleTools:

    def test_role_tools_returns_mapped(self):
        data = _full_yaml()
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.get_role_tools("coder") == ["validate_csharp"]
        assert m.get_role_tools("reviewer") == []

    def test_role_tools_default_all(self):
        data = _minimal_yaml()
        data["tools"] = [
            {"module": "t.py", "class": "T1", "name": "tool_a"},
            {"module": "t.py", "class": "T2", "name": "tool_b"},
        ]
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.get_role_tools("coder") == ["tool_a", "tool_b"]

    def test_role_tools_unknown_role_returns_all(self):
        data = _full_yaml()
        # "tester" is not in roles dict
        m = SkillManifest.from_yaml_dict(data, "/tmp", "bundled")
        assert m.get_role_tools("tester") == ["validate_csharp"]
