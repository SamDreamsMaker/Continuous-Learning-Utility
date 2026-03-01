"""Tests for skills daemon integration — HeartbeatManager + AgentDaemon with skills."""

import os
import tempfile
import textwrap

import pytest
import yaml

from skills.manifest import SkillManifest
from skills.manager import SkillManager
from daemon.heartbeat import HeartbeatManager, HeartbeatConfig
from daemon.task_queue import TaskQueue


# --- Helpers ---

def _make_manifest(name="test-skill", skill_dir="/tmp", **kwargs) -> SkillManifest:
    data = {"name": name, "version": "1.0.0"}
    data.update(kwargs)
    return SkillManifest.from_yaml_dict(data, skill_dir, "bundled")


def _make_check_module(td: str, check_name: str, ok: bool = True, issues: list = None) -> str:
    """Write a simple check module that returns a fixed result."""
    issues_repr = repr(issues or [])
    code = textwrap.dedent(f"""\
        from daemon.checks.base import CheckResult
        name = "{check_name}"
        def run(project_path, **kwargs):
            return CheckResult(
                check_name=name,
                ok={ok},
                issues={issues_repr},
                summary="skill check result",
            )
    """)
    path = os.path.join(td, f"{check_name}.py")
    with open(path, "w") as f:
        f.write(code)
    return path


# --- HeartbeatManager skill check registration ---

class TestHeartbeatSkillChecks:

    def _make_heartbeat(self) -> HeartbeatManager:
        queue = TaskQueue()
        return HeartbeatManager(queue=queue, config=HeartbeatConfig(enabled=False, checks=[]))

    def test_register_no_skills_returns_zero(self):
        hb = self._make_heartbeat()
        mgr = SkillManager.empty()
        count = hb.register_skill_checks(mgr)
        assert count == 0

    def test_register_skill_check_succeeds(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        check_path = _make_check_module(str(skill_dir), "my_check")

        data = {
            "name": "my-skill",
            "version": "1.0.0",
            "checks": [{"module": "my_check.py", "name": "my_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        hb = self._make_heartbeat()
        count = hb.register_skill_checks(mgr)
        assert count == 1
        assert "my_check" in hb._skill_checks

    def test_register_check_missing_module_skipped(self, tmp_path):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()

        data = {
            "name": "bad-skill",
            "version": "1.0.0",
            "checks": [{"module": "nonexistent.py", "name": "missing_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        hb = self._make_heartbeat()
        count = hb.register_skill_checks(mgr)
        assert count == 0

    def test_register_check_no_run_fn_skipped(self, tmp_path):
        skill_dir = tmp_path / "no-run"
        skill_dir.mkdir()
        # Module with no run() function
        with open(skill_dir / "bad_check.py", "w") as f:
            f.write("name = 'bad_check'\n")

        data = {
            "name": "no-run",
            "version": "1.0.0",
            "checks": [{"module": "bad_check.py", "name": "bad_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        hb = self._make_heartbeat()
        count = hb.register_skill_checks(mgr)
        assert count == 0

    def test_skill_check_runs_during_tick(self, tmp_path):
        """Skill checks should be called during heartbeat tick."""
        skill_dir = tmp_path / "tick-skill"
        skill_dir.mkdir()
        _make_check_module(str(skill_dir), "my_tick_check", ok=True)

        # Create a dummy project directory for tick()
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        data = {
            "name": "tick-skill",
            "version": "1.0.0",
            "checks": [{"module": "my_tick_check.py", "name": "my_tick_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        queue = TaskQueue()
        hb = HeartbeatManager(
            queue=queue,
            config=HeartbeatConfig(enabled=True, checks=[]),  # no built-in checks
        )
        hb.register_skill_checks(mgr)

        results = hb.tick(str(project_dir))

        check_names = [r.check_name for r in results]
        assert "my_tick_check" in check_names

    def test_skill_check_issue_triggers_auto_enqueue(self, tmp_path):
        """Skill check returning issues should auto-enqueue a fix task."""
        skill_dir = tmp_path / "issue-skill"
        skill_dir.mkdir()
        _make_check_module(
            str(skill_dir), "broken_check",
            ok=False,
            issues=[{"file": "src/main.py", "message": "Import error"}],
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()

        data = {
            "name": "issue-skill",
            "version": "1.0.0",
            "checks": [{"module": "broken_check.py", "name": "broken_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        queue = TaskQueue()
        hb = HeartbeatManager(
            queue=queue,
            config=HeartbeatConfig(
                enabled=True,
                checks=[],
                auto_fix_on_error=True,
                max_auto_tasks_per_hour=10,
            ),
        )
        hb.register_skill_checks(mgr)

        initial_count = queue.stats()["total"]
        hb.tick(str(project_dir))
        final_count = queue.stats()["total"]

        assert final_count > initial_count  # fix task was enqueued


# --- AgentDaemon skill_manager wiring ---

class TestDaemonSkillManagerWiring:

    def test_daemon_accepts_skill_manager(self):
        from orchestrator.config import AgentConfig
        from daemon.daemon import AgentDaemon

        config = AgentConfig()
        mgr = SkillManager.empty()
        daemon = AgentDaemon(config=config, skill_manager=mgr)
        assert daemon.skill_manager is mgr

    def test_daemon_default_skill_manager_is_empty(self):
        from orchestrator.config import AgentConfig
        from daemon.daemon import AgentDaemon

        config = AgentConfig()
        daemon = AgentDaemon(config=config)
        assert daemon.skill_manager.skill_count == 0

    def test_daemon_registers_skill_checks_on_init(self, tmp_path):
        """AgentDaemon should call heartbeat.register_skill_checks() during __init__."""
        from orchestrator.config import AgentConfig
        from daemon.daemon import AgentDaemon

        skill_dir = tmp_path / "check-skill"
        skill_dir.mkdir()
        _make_check_module(str(skill_dir), "daemon_check")

        data = {
            "name": "check-skill",
            "version": "1.0.0",
            "checks": [{"module": "daemon_check.py", "name": "daemon_check"}],
        }
        m = SkillManifest.from_yaml_dict(data, str(skill_dir), "bundled")
        mgr = SkillManager([m])

        config = AgentConfig()
        daemon = AgentDaemon(config=config, skill_manager=mgr)

        assert "daemon_check" in daemon.heartbeat._skill_checks
