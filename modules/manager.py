"""Module manager: discover, load, start, stop CLU modules."""

import importlib.util
import logging
import os
import sys

from modules.base import BaseModule, ModuleContext, ModuleManifest

logger = logging.getLogger(__name__)

BUNDLED_DIR = os.path.join(os.path.dirname(__file__), "bundled")
USER_DIR = os.path.join(os.path.expanduser("~"), ".clu", "modules")


class ModuleManager:
    """Discovers, loads, and manages the lifecycle of CLU modules."""

    def __init__(
        self,
        modules_config: dict,
        task_queue=None,
        alert_manager=None,
        project_path: str = "",
        app=None,
    ):
        self._config = modules_config
        self._task_queue = task_queue
        self._alert_manager = alert_manager
        self._project_path = project_path
        self._app = app

        self._manifests: dict[str, ModuleManifest] = {}
        self._instances: dict[str, BaseModule] = {}
        self._running: set[str] = set()

    # ---- Discovery ----

    def discover(self, project_path: str | None = None) -> list[ModuleManifest]:
        """Scan bundled → user → project module directories.

        Higher tiers override lower by name.
        """
        found: dict[str, ModuleManifest] = {}

        scan_dirs = [
            (BUNDLED_DIR, "bundled"),
            (USER_DIR, "user"),
        ]
        if project_path:
            proj_modules = os.path.join(project_path, ".clu", "modules")
            scan_dirs.append((proj_modules, "project"))

        for base_dir, tier in scan_dirs:
            if not os.path.isdir(base_dir):
                continue
            for entry in sorted(os.listdir(base_dir)):
                manifest_path = os.path.join(base_dir, entry, "module.yaml")
                if not os.path.isfile(manifest_path):
                    continue
                try:
                    manifest = ModuleManifest.from_yaml(manifest_path, tier=tier)
                    found[manifest.name] = manifest  # higher tier overwrites
                    logger.debug("Discovered module: %s (%s)", manifest.name, tier)
                except Exception as e:
                    logger.warning("Failed to load module manifest %s: %s", manifest_path, e)

        self._manifests = found
        return list(found.values())

    # ---- Loading ----

    def _load_module(self, manifest: ModuleManifest) -> BaseModule:
        """Import and instantiate a module from its manifest."""
        handler_path = os.path.join(manifest.path, manifest.entry_point)
        if not os.path.isfile(handler_path):
            raise FileNotFoundError(f"Module entry point not found: {handler_path}")

        # Dynamic import
        spec = importlib.util.spec_from_file_location(
            f"clu_module_{manifest.name}", handler_path
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)

        # Find the class
        class_name = manifest.class_name
        if not class_name:
            # Auto-detect: first BaseModule subclass in the file
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseModule)
                    and attr is not BaseModule
                ):
                    class_name = attr_name
                    break
        if not class_name:
            raise ValueError(f"No BaseModule subclass found in {handler_path}")

        cls = getattr(mod, class_name)
        return cls()

    # ---- Lifecycle ----

    async def start_all(self) -> dict[str, bool]:
        """Start all enabled modules. Returns {name: success}."""
        results = {}
        for name, manifest in self._manifests.items():
            module_config = self._config.get(name, {})
            if not module_config.get("enabled", True):
                logger.info("Module '%s' is disabled, skipping", name)
                results[name] = False
                continue
            results[name] = await self.start_one(name)
        return results

    async def start_one(self, name: str) -> bool:
        """Start a single module by name."""
        if name in self._running:
            logger.warning("Module '%s' is already running", name)
            return True

        manifest = self._manifests.get(name)
        if not manifest:
            logger.error("Module '%s' not found", name)
            return False

        try:
            instance = self._load_module(manifest)
            module_config = self._config.get(name, {})
            ctx = ModuleContext(
                task_queue=self._task_queue,
                alert_manager=self._alert_manager,
                config=module_config,
                project_path=self._project_path,
                app=self._app,
            )
            await instance.start(ctx)
            self._instances[name] = instance
            self._running.add(name)
            logger.info("Module started: %s (%s)", name, manifest.module_type)
            return True
        except Exception as e:
            logger.error("Failed to start module '%s': %s", name, e)
            return False

    async def stop_one(self, name: str) -> bool:
        """Stop a single module."""
        if name not in self._running:
            return False
        instance = self._instances.get(name)
        if not instance:
            return False
        try:
            await instance.stop()
        except Exception as e:
            logger.warning("Error stopping module '%s': %s", name, e)
        self._running.discard(name)
        self._instances.pop(name, None)
        logger.info("Module stopped: %s", name)
        return True

    async def stop_all(self) -> None:
        """Graceful shutdown of all running modules."""
        for name in list(self._running):
            await self.stop_one(name)

    # ---- Status ----

    def status(self) -> list[dict]:
        """Status of all discovered modules."""
        result = []
        for name, manifest in self._manifests.items():
            module_config = self._config.get(name, {})
            info = manifest.to_dict()
            info["enabled"] = module_config.get("enabled", True)
            info["running"] = name in self._running
            instance = self._instances.get(name)
            if instance:
                try:
                    info["status"] = instance.status()
                except Exception:
                    info["status"] = {"running": True}
            result.append(info)
        return result

    def get(self, name: str) -> BaseModule | None:
        return self._instances.get(name)

    @property
    def module_count(self) -> int:
        return len(self._manifests)

    @property
    def running_count(self) -> int:
        return len(self._running)
