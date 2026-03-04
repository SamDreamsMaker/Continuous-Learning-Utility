"""Tests for ModuleManager: discover, start/stop lifecycle, manifest, tiers."""

import asyncio
import os
import pytest
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.manager import ModuleManager
from modules.base import BaseModule, ModuleContext, ModuleManifest


# ---- Test fixtures ----

def _create_module_dir(base_path, name, manifest_extra=None, handler_code=None):
    """Helper to create a module directory with manifest and handler."""
    mod_dir = base_path / name
    mod_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": f"Test module {name}",
        "type": "notifier",
        "entry_point": "handler.py",
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    (mod_dir / "module.yaml").write_text(yaml.dump(manifest), encoding="utf-8")

    code = handler_code or (
        "from modules.base import BaseModule\n\n"
        "class TestHandler(BaseModule):\n"
        f"    @property\n"
        f"    def name(self): return '{name}'\n"
        "    async def start(self, ctx): self._started = True\n"
        "    async def stop(self): self._started = False\n"
        "    def status(self): return {'running': getattr(self, '_started', False)}\n"
    )
    (mod_dir / "handler.py").write_text(code, encoding="utf-8")
    return mod_dir


@pytest.fixture
def bundled_dir(tmp_path):
    d = tmp_path / "bundled"
    d.mkdir()
    return d


@pytest.fixture
def user_dir(tmp_path):
    d = tmp_path / "user"
    d.mkdir()
    return d


@pytest.fixture
def manager(bundled_dir):
    return ModuleManager(modules_config={})


# ---- Discovery tests ----

class TestModuleDiscovery:

    def test_discover_empty(self, tmp_path):
        mgr = ModuleManager(modules_config={})
        manifests = mgr.discover(str(tmp_path))
        # Only finds modules in BUNDLED_DIR / USER_DIR / project .clu/modules
        # tmp_path has no .clu/modules, so only system dirs count
        # Just verify it doesn't crash
        assert isinstance(manifests, list)

    def test_discover_bundled(self, bundled_dir, monkeypatch):
        _create_module_dir(bundled_dir, "test-mod")
        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(bundled_dir.parent / "nonexistent"))

        mgr = ModuleManager(modules_config={})
        manifests = mgr.discover()
        names = [m.name for m in manifests]
        assert "test-mod" in names

    def test_tier_override(self, bundled_dir, user_dir, monkeypatch):
        """User tier overrides bundled tier for same module name."""
        _create_module_dir(bundled_dir, "overlap",
                           manifest_extra={"description": "bundled version"})
        _create_module_dir(user_dir, "overlap",
                           manifest_extra={"description": "user version"})

        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(user_dir))

        mgr = ModuleManager(modules_config={})
        manifests = mgr.discover()
        overlap = [m for m in manifests if m.name == "overlap"]
        assert len(overlap) == 1
        assert overlap[0].tier == "user"


# ---- Lifecycle tests ----

class TestModuleLifecycle:

    @pytest.fixture
    def mgr_with_mod(self, bundled_dir, monkeypatch):
        _create_module_dir(bundled_dir, "mymod")
        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(bundled_dir.parent / "nonexistent"))

        mgr = ModuleManager(modules_config={"mymod": {"enabled": True}})
        mgr.discover()
        return mgr

    def test_start_and_stop(self, mgr_with_mod):
        result = asyncio.run(mgr_with_mod.start_one("mymod"))
        assert result is True
        assert mgr_with_mod.running_count == 1

        result = asyncio.run(mgr_with_mod.stop_one("mymod"))
        assert result is True
        assert mgr_with_mod.running_count == 0

    def test_start_nonexistent(self, mgr_with_mod):
        result = asyncio.run(mgr_with_mod.start_one("nope"))
        assert result is False

    def test_start_already_running(self, mgr_with_mod):
        asyncio.run(mgr_with_mod.start_one("mymod"))
        result = asyncio.run(mgr_with_mod.start_one("mymod"))
        assert result is True  # already running, returns True

    def test_stop_not_running(self, mgr_with_mod):
        result = asyncio.run(mgr_with_mod.stop_one("mymod"))
        assert result is False

    def test_start_all_skips_disabled(self, bundled_dir, monkeypatch):
        _create_module_dir(bundled_dir, "enabled-mod")
        _create_module_dir(bundled_dir, "disabled-mod")
        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(bundled_dir.parent / "nonexistent"))

        mgr = ModuleManager(modules_config={
            "enabled-mod": {"enabled": True},
            "disabled-mod": {"enabled": False},
        })
        mgr.discover()
        results = asyncio.run(mgr.start_all())
        assert results["enabled-mod"] is True
        assert results["disabled-mod"] is False


# ---- Status tests ----

class TestModuleStatus:

    def test_status_report(self, bundled_dir, monkeypatch):
        _create_module_dir(bundled_dir, "mymod")
        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(bundled_dir.parent / "nonexistent"))

        mgr = ModuleManager(modules_config={"mymod": {"enabled": True}})
        mgr.discover()

        status = mgr.status()
        assert len(status) >= 1
        mymod_status = [s for s in status if s["name"] == "mymod"][0]
        assert mymod_status["enabled"] is True
        assert mymod_status["running"] is False

    def test_module_count(self, bundled_dir, monkeypatch):
        _create_module_dir(bundled_dir, "mod1")
        _create_module_dir(bundled_dir, "mod2")
        monkeypatch.setattr("modules.manager.BUNDLED_DIR", str(bundled_dir))
        monkeypatch.setattr("modules.manager.USER_DIR", str(bundled_dir.parent / "nonexistent"))

        mgr = ModuleManager(modules_config={})
        mgr.discover()
        assert mgr.module_count == 2
        assert mgr.running_count == 0
