"""Configuration management for the agent."""

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class AgentConfig:
    """Agent configuration loaded from YAML."""

    # Project profile
    project_name: str = "generic"
    project_language: str = "any"
    project_file_extensions: list[str] = field(default_factory=list)
    project_source_dir: str = ""
    project_framework: str = "generic"

    # API settings
    provider: str = "openai_compat"  # openai_compat | anthropic | google
    api_base: str = "http://localhost:1234/v1"
    api_key: str = ""  # empty = env var or "not-needed" for local
    model: str = "qwen/qwen3-coder-30b"

    # LLM settings
    temperature: float = 0
    seed: int = 42
    max_tokens: int = 4096
    llm_profile: str = "auto"  # "auto" | "compact" | "default"

    # Budget settings
    max_iterations: int = 50
    max_total_tokens: int = 500_000
    max_context_tokens: int = 32_000

    # Security settings
    allowed_path_prefix: str = ""
    blocked_prefixes: list[str] = field(default_factory=lambda: [
        "C:/Windows", "C:/Program Files", "C:/Program Files (x86)",
        "/etc", "/bin", "/usr", "/sys", "/proc",
        ".git",
    ])
    write_blocked_prefixes: list[str] = field(default_factory=lambda: [
        ".clu",
    ])

    # Validation settings
    unity_dll_path: str = ""  # Set in config/profiles/unity.yaml to your Unity install path
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
    # Community registry
    skills_registry_url: str = "https://github.com/clu-community/clu-skills"
    skills_registry_sync_enabled: bool = False   # pull community skills automatically
    skills_registry_sync_interval: int = 86400   # seconds between syncs (24h)
    # Auto-generation
    skills_auto_generate: bool = True            # generate skills from patterns
    skills_auto_publish: bool = False            # push generated skills to registry
    skills_github_token: str = ""               # PAT with repo scope (publishing)
    skills_generate_after_n_tasks: int = 10     # analyze every N completed tasks
    skills_generate_min_occurrences: int = 3    # pattern must appear this many times
    skills_generate_min_success_rate: float = 0.7  # min success rate for candidate

    # Modules
    modules_enabled: bool = True
    modules_auto_start: bool = True
    modules_config: dict = field(default_factory=dict)  # per-module config

    def _resolve_secrets(self):
        """Resolve secret fields from OS keyring / env vars."""
        from orchestrator.secrets import get_secret, is_secret_field

        for field_name in list(vars(self)):
            if is_secret_field(field_name) and isinstance(getattr(self, field_name), str):
                current = getattr(self, field_name)
                resolved = get_secret(field_name, current)
                setattr(self, field_name, resolved)

        # Also resolve secrets in per-module config dicts
        for mod_name, mod_cfg in self.modules_config.items():
            if not isinstance(mod_cfg, dict):
                continue
            for key, val in mod_cfg.items():
                if is_secret_field(key) and isinstance(val, str):
                    mod_cfg[key] = get_secret(f"{mod_name}_{key}", val)

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
        modules_section = data.get("modules", {})

        config = cls(
            project_name=project.get("name", cls.project_name),
            project_language=project.get("language", cls.project_language),
            project_file_extensions=project.get("file_extensions", []),
            project_source_dir=project.get("source_dir", cls.project_source_dir),
            project_framework=project.get("framework", cls.project_framework),
            provider=api.get("provider", cls.provider),
            api_base=api.get("base_url", cls.api_base),
            api_key=api.get("api_key", cls.api_key),
            model=api.get("model", cls.model),
            temperature=llm.get("temperature", cls.temperature),
            seed=llm.get("seed", cls.seed),
            max_tokens=llm.get("max_tokens", cls.max_tokens),
            llm_profile=llm.get("profile", cls.llm_profile),
            max_iterations=budget.get("max_iterations", cls.max_iterations),
            max_total_tokens=budget.get("max_total_tokens", cls.max_total_tokens),
            max_context_tokens=budget.get("max_context_tokens", cls.max_context_tokens),
            allowed_path_prefix=security.get("allowed_path_prefix", cls.allowed_path_prefix),
            blocked_prefixes=security.get("blocked_prefixes", [
                "C:/Windows", "C:/Program Files", "C:/Program Files (x86)",
                "/etc", "/bin", "/usr", "/sys", "/proc",
                ".git",
            ]),
            write_blocked_prefixes=security.get("write_blocked_prefixes", [".clu"]),
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
            skills_registry_url=skills_section.get("registry_url", cls.skills_registry_url),
            skills_registry_sync_enabled=skills_section.get("registry_sync_enabled", cls.skills_registry_sync_enabled),
            skills_registry_sync_interval=skills_section.get("registry_sync_interval", cls.skills_registry_sync_interval),
            skills_auto_generate=skills_section.get("auto_generate", cls.skills_auto_generate),
            skills_auto_publish=skills_section.get("auto_publish", cls.skills_auto_publish),
            skills_github_token=skills_section.get("github_token", cls.skills_github_token),
            skills_generate_after_n_tasks=skills_section.get("generate_after_n_tasks", cls.skills_generate_after_n_tasks),
            skills_generate_min_occurrences=skills_section.get("generate_min_occurrences", cls.skills_generate_min_occurrences),
            skills_generate_min_success_rate=skills_section.get("generate_min_success_rate", cls.skills_generate_min_success_rate),
            modules_enabled=modules_section.get("enabled", cls.modules_enabled),
            modules_auto_start=modules_section.get("auto_start", cls.modules_auto_start),
            modules_config={k: v for k, v in modules_section.items() if isinstance(v, dict)},
        )

        # Resolve secrets from OS keyring / env vars
        config._resolve_secrets()
        return config


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
