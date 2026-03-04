"""Tests for skills config — AgentConfig skills fields + YAML round-trip."""

import os
import tempfile

import pytest
import yaml

from orchestrator.config import AgentConfig


class TestSkillsConfigDefaults:

    def test_default_skills_enabled(self):
        config = AgentConfig()
        assert config.skills_enabled is True

    def test_default_skills_user_dir_empty(self):
        config = AgentConfig()
        assert config.skills_user_dir == ""

    def test_default_skills_project_dir_empty(self):
        config = AgentConfig()
        assert config.skills_project_dir == ""

    def test_default_skills_prompt_budget(self):
        config = AgentConfig()
        assert config.skills_prompt_budget == 12_000


class TestSkillsConfigFromDict:

    def test_skills_enabled_false(self):
        config = AgentConfig.from_dict({"skills": {"enabled": False}})
        assert config.skills_enabled is False

    def test_skills_user_dir(self):
        config = AgentConfig.from_dict({"skills": {"user_dir": "/custom/user/skills"}})
        assert config.skills_user_dir == "/custom/user/skills"

    def test_skills_project_dir(self):
        config = AgentConfig.from_dict({"skills": {"project_dir": ".clu/skills"}})
        assert config.skills_project_dir == ".clu/skills"

    def test_skills_prompt_budget(self):
        config = AgentConfig.from_dict({"skills": {"prompt_budget": 5000}})
        assert config.skills_prompt_budget == 5000

    def test_skills_section_absent_uses_defaults(self):
        config = AgentConfig.from_dict({})
        assert config.skills_enabled is True
        assert config.skills_prompt_budget == 12_000

    def test_partial_skills_section_uses_defaults_for_missing(self):
        config = AgentConfig.from_dict({"skills": {"enabled": False}})
        assert config.skills_enabled is False
        assert config.skills_prompt_budget == 12_000  # default preserved


class TestSkillsConfigFromYaml:

    def test_yaml_roundtrip_skills_section(self):
        data = {
            "skills": {
                "enabled": True,
                "user_dir": "/home/user/.clu/skills",
                "project_dir": ".clu/skills",
                "prompt_budget": 8000,
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump(data, f)
            tmppath = f.name

        try:
            config = AgentConfig.from_yaml(tmppath)
            assert config.skills_enabled is True
            assert config.skills_user_dir == "/home/user/.clu/skills"
            assert config.skills_project_dir == ".clu/skills"
            assert config.skills_prompt_budget == 8000
        finally:
            os.unlink(tmppath)

    def test_default_yaml_has_skills_section(self):
        """The bundled default.yaml should contain a valid skills section."""
        default_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "default.yaml"
        )
        config = AgentConfig.from_yaml(default_path)
        assert isinstance(config.skills_enabled, bool)
        assert isinstance(config.skills_prompt_budget, int)
        assert config.skills_prompt_budget > 0


class TestSkillsConfigResolution:
    """Test that AgentConfig skills fields drive correct SkillLoader construction."""

    def test_skills_disabled_manager_is_empty(self):
        """When skills_enabled=False, no skills should be loaded."""
        from skills.loader import SkillLoader
        from skills.manager import SkillManager

        config = AgentConfig.from_dict({"skills": {"enabled": False}})
        assert config.skills_enabled is False

        # Simulate the factory pattern: disabled → empty manager
        if not config.skills_enabled:
            mgr = SkillManager.empty()
        else:
            loader = SkillLoader(
                user_skills_dir=config.skills_user_dir or None,
                project_skills_dir=config.skills_project_dir or None,
            )
            mgr = SkillManager.from_loader(loader)

        assert mgr.skill_count == 0

    def test_skills_enabled_builds_manager(self, tmp_path):
        """When skills_enabled=True, manager is built from loader."""
        import yaml as _yaml
        from skills.loader import SkillLoader
        from skills.manager import SkillManager

        # Write a skill in the user dir
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            _yaml.dump({"name": "my-skill", "version": "1.0.0"})
        )

        config = AgentConfig.from_dict({
            "skills": {
                "enabled": True,
                "user_dir": str(tmp_path),
            }
        })

        loader = SkillLoader(
            user_skills_dir=config.skills_user_dir or None,
            project_skills_dir=config.skills_project_dir or None,
        )
        # Isolate from real bundled + registry skills in test
        loader.BUNDLED_DIR = str(tmp_path / "nonexistent")
        loader.registry_dir = str(tmp_path / "nonexistent_registry")
        mgr = SkillManager.from_loader(loader)

        assert mgr.skill_count == 1
        assert mgr.get_skill("my-skill") is not None

    def test_prompt_budget_from_config_passed_to_manager(self):
        """Verify skills_prompt_budget is accessible for use by AgentRunner."""
        config = AgentConfig.from_dict({"skills": {"prompt_budget": 7777}})
        assert config.skills_prompt_budget == 7777
        # In production, AgentRunner would use this: mgr.get_prompt_injections(task, budget_chars=config.skills_prompt_budget)
