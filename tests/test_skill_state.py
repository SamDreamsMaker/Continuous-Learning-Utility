"""Tests for skills.state — SkillStateStore enable/disable and persistence."""

import json
import os
import tempfile

import pytest

from skills.state import SkillStateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store(tmp_dir: str) -> SkillStateStore:
    """Create a fresh SkillStateStore backed by a temp path."""
    return SkillStateStore(state_path=os.path.join(tmp_dir, "skills-state.json"))


# ---------------------------------------------------------------------------
# Default state (nothing configured)
# ---------------------------------------------------------------------------

class TestDefaults:

    def test_all_skills_enabled_by_default(self, tmp_path):
        store = _store(str(tmp_path))
        assert store.is_enabled("unity-support") is True
        assert store.is_enabled("code-conventions") is True

    def test_auto_generate_returns_none_by_default(self, tmp_path):
        store = _store(str(tmp_path))
        assert store.get_auto_generate() is None

    def test_disabled_names_empty_by_default(self, tmp_path):
        store = _store(str(tmp_path))
        assert store.disabled_names() == set()


# ---------------------------------------------------------------------------
# Enable / Disable
# ---------------------------------------------------------------------------

class TestEnableDisable:

    def test_disable_skill(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_enabled("unity-support", False)
        assert store.is_enabled("unity-support") is False

    def test_enable_skill_after_disable(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_enabled("unity-support", False)
        store.set_enabled("unity-support", True)
        assert store.is_enabled("unity-support") is True

    def test_enable_never_disabled_skill_is_noop(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_enabled("never-disabled", True)
        assert store.is_enabled("never-disabled") is True
        assert "never-disabled" not in store.disabled_names()

    def test_disable_multiple_skills(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_enabled("skill-a", False)
        store.set_enabled("skill-b", False)
        assert store.is_enabled("skill-a") is False
        assert store.is_enabled("skill-b") is False
        assert store.is_enabled("skill-c") is True

    def test_disabled_names_reflects_state(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_enabled("x", False)
        store.set_enabled("y", False)
        store.set_enabled("x", True)
        disabled = store.disabled_names()
        assert "x" not in disabled
        assert "y" in disabled


# ---------------------------------------------------------------------------
# Auto-generate toggle
# ---------------------------------------------------------------------------

class TestAutoGenerate:

    def test_set_auto_generate_true(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_auto_generate(True)
        assert store.get_auto_generate() is True

    def test_set_auto_generate_false(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_auto_generate(False)
        assert store.get_auto_generate() is False

    def test_toggle_auto_generate(self, tmp_path):
        store = _store(str(tmp_path))
        store.set_auto_generate(True)
        store.set_auto_generate(False)
        assert store.get_auto_generate() is False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_disabled_skill_persists_across_reload(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        store1 = SkillStateStore(state_path=path)
        store1.set_enabled("unity-support", False)

        store2 = SkillStateStore(state_path=path)
        assert store2.is_enabled("unity-support") is False

    def test_re_enabled_skill_persists(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        store1 = SkillStateStore(state_path=path)
        store1.set_enabled("unity-support", False)
        store1.set_enabled("unity-support", True)

        store2 = SkillStateStore(state_path=path)
        assert store2.is_enabled("unity-support") is True

    def test_auto_generate_persists(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        store1 = SkillStateStore(state_path=path)
        store1.set_auto_generate(False)

        store2 = SkillStateStore(state_path=path)
        assert store2.get_auto_generate() is False

    def test_state_file_is_valid_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        store = SkillStateStore(state_path=path)
        store.set_enabled("skill-a", False)
        store.set_auto_generate(True)

        with open(path) as f:
            data = json.load(f)

        assert "disabled" in data
        assert "skill-a" in data["disabled"]
        assert data["auto_generate"] is True
        assert "updated_at" in data

    def test_load_from_missing_file_is_safe(self, tmp_path):
        path = os.path.join(str(tmp_path), "nonexistent.json")
        store = SkillStateStore(state_path=path)
        assert store.is_enabled("anything") is True
        assert store.get_auto_generate() is None

    def test_load_from_corrupt_file_is_safe(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        with open(path, "w") as f:
            f.write("not valid json {{")
        store = SkillStateStore(state_path=path)
        assert store.is_enabled("anything") is True

    def test_disabled_list_is_sorted_in_file(self, tmp_path):
        path = os.path.join(str(tmp_path), "skills-state.json")
        store = SkillStateStore(state_path=path)
        store.set_enabled("z-skill", False)
        store.set_enabled("a-skill", False)
        store.set_enabled("m-skill", False)

        with open(path) as f:
            data = json.load(f)

        assert data["disabled"] == sorted(data["disabled"])


# ---------------------------------------------------------------------------
# Integration with SkillManager
# ---------------------------------------------------------------------------

class TestSkillManagerIntegration:

    def _make_manifest(self, name="test-skill"):
        from skills.manifest import SkillManifest
        return SkillManifest.from_yaml_dict(
            {"name": name, "version": "1.0.0"}, "/tmp", "bundled"
        )

    def test_summary_includes_enabled_field(self, tmp_path):
        from skills.manager import SkillManager
        store = _store(str(tmp_path))
        m = self._make_manifest("skill-a")
        mgr = SkillManager([m], state_store=store)
        items = mgr.summary()
        assert len(items) == 1
        assert items[0]["enabled"] is True

    def test_disabled_skill_marked_in_summary(self, tmp_path):
        from skills.manager import SkillManager
        store = _store(str(tmp_path))
        store.set_enabled("skill-a", False)
        m = self._make_manifest("skill-a")
        mgr = SkillManager([m], state_store=store)
        items = mgr.summary()
        assert items[0]["enabled"] is False

    def test_disabled_skill_excluded_from_prompt_injection(self, tmp_path):
        import os
        import yaml
        from skills.manager import SkillManager
        from skills.manifest import SkillManifest

        skill_dir = os.path.join(str(tmp_path), "my-skill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
            f.write("Secret Unity tips you should not see when disabled.")
        data = {
            "name": "my-skill",
            "version": "1.0.0",
            "prompt": {"file": "prompt.md", "budget": 5000, "keywords": ["unity"]},
        }
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            yaml.dump(data, f)
        m = SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

        store = _store(str(tmp_path))
        store.set_enabled("my-skill", False)
        mgr = SkillManager([m], state_store=store)

        result = mgr.get_prompt_injections("Fix a Unity compile error")
        assert "Secret Unity tips" not in result

    def test_enabled_skill_included_in_prompt_injection(self, tmp_path):
        import os
        import yaml
        from skills.manager import SkillManager
        from skills.manifest import SkillManifest

        skill_dir = os.path.join(str(tmp_path), "my-skill")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "prompt.md"), "w") as f:
            f.write("Unity tips you should see when enabled.")
        data = {
            "name": "my-skill",
            "version": "1.0.0",
            "prompt": {"file": "prompt.md", "budget": 5000, "keywords": ["unity"]},
        }
        with open(os.path.join(skill_dir, "skill.yaml"), "w") as f:
            yaml.dump(data, f)
        m = SkillManifest.from_yaml_dict(data, skill_dir, "bundled")

        store = _store(str(tmp_path))
        # skill is enabled by default
        mgr = SkillManager([m], state_store=store)

        result = mgr.get_prompt_injections("Fix a Unity compile error")
        assert "Unity tips you should see when enabled." in result

    def test_no_state_store_all_enabled(self):
        from skills.manager import SkillManager
        m = self._make_manifest("some-skill")
        mgr = SkillManager([m])  # no state_store
        items = mgr.summary()
        assert items[0]["enabled"] is True
