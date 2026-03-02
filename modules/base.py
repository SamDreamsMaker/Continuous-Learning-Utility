"""Module system base classes for CLU integrations.

Modules extend CLU with external integrations (receivers, notifiers, bridges)
that go beyond what skills can do. Skills extend the agent (prompts, tools).
Modules extend CLU itself (new input/output channels, background services).
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import yaml


# Valid module types
MODULE_TYPES = ("receiver", "notifier", "bridge")


@dataclass
class ModuleManifest:
    """Metadata parsed from module.yaml."""

    name: str
    version: str = "1.0.0"
    module_type: str = "notifier"  # receiver | notifier | bridge
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)
    entry_point: str = "handler.py"
    class_name: str = ""
    # Internal: set by discovery
    path: str = ""  # absolute path to module directory
    tier: str = ""  # bundled | user | project

    @classmethod
    def from_yaml(cls, yaml_path: str, tier: str = "") -> "ModuleManifest":
        """Load manifest from a module.yaml file."""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        name = data.get("name", "")
        if not name:
            raise ValueError(f"Module manifest missing 'name': {yaml_path}")

        module_type = data.get("type", "notifier")
        if module_type not in MODULE_TYPES:
            raise ValueError(f"Invalid module type '{module_type}' in {yaml_path}")

        return cls(
            name=name,
            version=data.get("version", "1.0.0"),
            module_type=module_type,
            description=data.get("description", ""),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            config_schema=data.get("config", {}),
            entry_point=data.get("entry_point", "handler.py"),
            class_name=data.get("class_name", ""),
            path=os.path.dirname(os.path.abspath(yaml_path)),
            tier=tier,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "type": self.module_type,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "tier": self.tier,
        }


class ModuleContext:
    """Controlled access to CLU internals for modules.

    Modules receive this on start() — it limits what they can access.
    """

    def __init__(
        self,
        task_queue,
        alert_manager,
        config: dict,
        project_path: str,
        app=None,
    ):
        self.task_queue = task_queue
        self.alert_manager = alert_manager
        self.config = config
        self.project_path = project_path
        self.app = app  # FastAPI app (for registering routes)
        self.logger = logging.getLogger("clu.modules")


class BaseModule(ABC):
    """Abstract base for all CLU modules.

    Subclasses implement start/stop for lifecycle management.
    The ModuleManager handles discovery, config loading, and orchestration.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module name (must match module.yaml name)."""

    @abstractmethod
    async def start(self, ctx: ModuleContext) -> None:
        """Initialize and start the module.

        Use ctx to access task_queue, alert_manager, config, app, etc.
        Register HTTP routes, start background tasks, open connections.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Clean shutdown. Close connections, cancel background tasks."""

    def status(self) -> dict:
        """Return module health/status info. Override for custom checks."""
        return {"running": True}
