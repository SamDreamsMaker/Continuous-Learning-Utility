"""Configuration management for the agent."""

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class AgentConfig:
    """Agent configuration loaded from YAML."""

    # Project profile
    project_name: str = "unity"
    project_language: str = "csharp"
    project_file_extensions: list[str] = field(default_factory=lambda: [".cs"])
    project_source_dir: str = "Assets/"
    project_framework: str = "unity"

    # API settings
    provider: str = "openai_compat"  # openai_compat | anthropic | google
    api_base: str = "http://localhost:1234/v1"
    api_key: str = ""  # empty = env var or "not-needed" for local
    model: str = "qwen/qwen3-coder-30b"

    # LLM settings
    temperature: float = 0
    seed: int = 42
    max_tokens: int = 4096

    # Budget settings
    max_iterations: int = 50
    max_total_tokens: int = 500_000
    max_context_tokens: int = 32_000

    # Security settings
    allowed_path_prefix: str = "Assets/"
    blocked_prefixes: list[str] = field(default_factory=lambda: [
        "Library/", "Packages/", "ProjectSettings/",
        "UserSettings/", "Temp/", "obj/", "Logs/", ".git/",
    ])

    # Validation settings
    unity_dll_path: str = "C:/Program Files/Unity/Hub/Editor/6000.0.58f2/Editor/Data/Managed/UnityEngine"
    dotnet_path: str = "dotnet"
    validation_timeout: int = 30
    validation_enabled: bool = True
    validation_validator: str = "csharp"  # "csharp" | "none"

    # Heartbeat settings
    heartbeat_enabled: bool = True
    heartbeat_interval: int = 300  # seconds
    heartbeat_auto_fix_compile: bool = True
    heartbeat_auto_fix_on_error: bool = True
    heartbeat_max_auto_tasks: int = 10  # per hour
    heartbeat_large_file_threshold: int = 300  # lines
    heartbeat_checks: list[str] = field(default_factory=lambda: [
        "unity_compile", "new_files", "todo_markers", "large_files",
    ])

    # Tools
    enabled_tools: list[str] = field(default_factory=lambda: [
        "think", "read_file", "list_files", "search_in_files",
        "write_file", "memory", "delegate", "validate_csharp",
        "unity_logs", "manage_schedules",
    ])

    # Path settings
    backup_dir: str = "backups"
    log_dir: str = "logs"
    prompts_dir: str = "prompts"

    # Skills settings
    skills_enabled: bool = True
    skills_user_dir: str = ""        # empty = default ~/.clu/skills
    skills_project_dir: str = ""     # empty = auto-detect .clu/skills in project
    skills_prompt_budget: int = 12_000

    @classmethod
    def from_yaml(cls, path: str) -> "AgentConfig":
        """Load configuration from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        """Create config from a nested dictionary."""
        project = data.get("project", {})
        api = data.get("api", {})
        llm = data.get("llm", {})
        budget = data.get("budget", {})
        security = data.get("security", {})
        validation = data.get("validation", {})
        heartbeat = data.get("heartbeat", {})
        tools_section = data.get("tools", {})
        paths = data.get("paths", {})
        skills_section = data.get("skills", {})

        return cls(
            project_name=project.get("name", cls.project_name),
            project_language=project.get("language", cls.project_language),
            project_file_extensions=project.get("file_extensions", [".cs"]),
            project_source_dir=project.get("source_dir", cls.project_source_dir),
            project_framework=project.get("framework", cls.project_framework),
            provider=api.get("provider", cls.provider),
            api_base=api.get("base_url", cls.api_base),
            api_key=api.get("api_key", cls.api_key),
            model=api.get("model", cls.model),
            temperature=llm.get("temperature", cls.temperature),
            seed=llm.get("seed", cls.seed),
            max_tokens=llm.get("max_tokens", cls.max_tokens),
            max_iterations=budget.get("max_iterations", cls.max_iterations),
            max_total_tokens=budget.get("max_total_tokens", cls.max_total_tokens),
            max_context_tokens=budget.get("max_context_tokens", cls.max_context_tokens),
            allowed_path_prefix=security.get("allowed_path_prefix", cls.allowed_path_prefix),
            blocked_prefixes=security.get("blocked_prefixes", [
                "Library/", "Packages/", "ProjectSettings/",
                "UserSettings/", "Temp/", "obj/", "Logs/", ".git/",
            ]),
            unity_dll_path=validation.get("unity_dll_path", cls.unity_dll_path),
            dotnet_path=validation.get("dotnet_path", cls.dotnet_path),
            validation_timeout=validation.get("validation_timeout", cls.validation_timeout),
            validation_enabled=validation.get("enabled", cls.validation_enabled),
            validation_validator=validation.get("validator", cls.validation_validator),
            heartbeat_enabled=heartbeat.get("enabled", cls.heartbeat_enabled),
            heartbeat_interval=heartbeat.get("interval", cls.heartbeat_interval),
            heartbeat_auto_fix_compile=heartbeat.get("auto_fix_compile_errors", cls.heartbeat_auto_fix_compile),
            heartbeat_auto_fix_on_error=heartbeat.get("auto_fix_on_error",
                heartbeat.get("auto_fix_compile_errors", cls.heartbeat_auto_fix_on_error)),
            heartbeat_max_auto_tasks=heartbeat.get("max_auto_tasks_per_hour", cls.heartbeat_max_auto_tasks),
            heartbeat_large_file_threshold=heartbeat.get("large_file_threshold", cls.heartbeat_large_file_threshold),
            heartbeat_checks=heartbeat.get("checks", [
                "unity_compile", "new_files", "todo_markers", "large_files",
            ]),
            enabled_tools=tools_section.get("enabled", [
                "think", "read_file", "list_files", "search_in_files",
                "write_file", "memory", "delegate", "validate_csharp",
                "unity_logs", "manage_schedules",
            ]),
            backup_dir=paths.get("backup_dir", cls.backup_dir),
            log_dir=paths.get("log_dir", cls.log_dir),
            prompts_dir=paths.get("prompts_dir", cls.prompts_dir),
            skills_enabled=skills_section.get("enabled", cls.skills_enabled),
            skills_user_dir=skills_section.get("user_dir", cls.skills_user_dir),
            skills_project_dir=skills_section.get("project_dir", cls.skills_project_dir),
            skills_prompt_budget=skills_section.get("prompt_budget", cls.skills_prompt_budget),
        )


# Module-level config singleton
_config: dict | None = None


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file and cache it."""
    global _config
    if path:
        with open(path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
    elif _config is None:
        default_path = os.path.join(os.path.dirname(__file__), "..", "config", "default.yaml")
        if os.path.isfile(default_path):
            with open(default_path, "r", encoding="utf-8") as f:
                _config = yaml.safe_load(f) or {}
        else:
            _config = {}
    return _config


def get_config() -> dict:
    """Get the cached config dict."""
    if _config is None:
        return load_config()
    return _config
