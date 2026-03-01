"""HeartbeatManager: runs periodic free checks and auto-enqueues tasks.

When the daemon's task queue is empty, the heartbeat kicks in every N seconds.
Each check is cheap (no LLM calls). If a check finds actionable issues
(e.g. compile errors), it enqueues a task for the agent to fix.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field

from daemon.checks.base import CheckResult
from daemon.checks import unity_compile, new_files, todo_markers, large_files
from daemon.task_queue import TaskQueue, TaskType

logger = logging.getLogger(__name__)

# State file for heartbeat metadata
_STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@dataclass
class HeartbeatConfig:
    """Heartbeat-specific configuration."""
    enabled: bool = True
    interval: int = 300  # seconds between heartbeat ticks
    auto_fix_compile_errors: bool = True  # backward compat
    auto_fix_on_error: bool = True
    max_auto_tasks_per_hour: int = 10
    large_file_threshold: int = 300
    checks: list[str] = field(default_factory=lambda: [
        "unity_compile", "new_files", "todo_markers", "large_files",
    ])
    source_dir: str = "Assets"
    file_extensions: list[str] = field(default_factory=lambda: [".cs"])


@dataclass
class HeartbeatStatus:
    """Current heartbeat state for API/UI."""
    last_tick: float | None = None
    last_results: list[dict] = field(default_factory=list)
    auto_tasks_enqueued: int = 0
    total_ticks: int = 0


class HeartbeatManager:
    """Runs all registered checks and auto-enqueues tasks when issues are found."""

    def __init__(
        self,
        queue: TaskQueue,
        config: HeartbeatConfig | None = None,
    ):
        self.queue = queue
        self.config = config or HeartbeatConfig()
        self._status = HeartbeatStatus()
        self._auto_task_times: list[float] = []  # timestamps of auto-enqueued tasks
        self._skill_checks: dict[str, object] = {}  # name -> run(project_path) -> CheckResult

    def register_skill_checks(self, skill_manager) -> int:
        """Register check contributions from a SkillManager.

        Args:
            skill_manager: SkillManager instance.

        Returns:
            Number of checks successfully registered.
        """
        import importlib.util

        registered = 0
        for manifest in skill_manager.skills:
            for entry in manifest.checks:
                module_path = os.path.join(manifest.skill_dir, entry.module)
                if not os.path.isfile(module_path):
                    logger.warning(
                        "Skill '%s' check module not found: %s",
                        manifest.name, module_path,
                    )
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"_skill_check_{manifest.name}_{entry.name}", module_path
                    )
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    run_fn = getattr(mod, "run", None)
                    if run_fn is None:
                        logger.warning(
                            "Skill '%s' check '%s': module has no run() function",
                            manifest.name, entry.name,
                        )
                        continue
                    self._skill_checks[entry.name] = run_fn
                    registered += 1
                    logger.debug(
                        "Registered skill check '%s' from skill '%s'",
                        entry.name, manifest.name,
                    )
                except Exception as e:
                    logger.warning(
                        "Skill '%s': failed to load check '%s': %s",
                        manifest.name, entry.name, e,
                    )
        return registered

    @property
    def status(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "interval": self.config.interval,
            "last_tick": self._status.last_tick,
            "total_ticks": self._status.total_ticks,
            "auto_tasks_enqueued": self._status.auto_tasks_enqueued,
            "last_results": self._status.last_results,
        }

    def should_tick(self) -> bool:
        """Check if enough time has passed since last heartbeat."""
        if not self.config.enabled:
            return False
        if self._status.last_tick is None:
            return True
        return (time.time() - self._status.last_tick) >= self.config.interval

    def tick(self, project_path: str) -> list[CheckResult]:
        """Run all checks against the project. Returns check results.

        Auto-enqueues fix tasks for actionable issues.
        """
        if not project_path or not os.path.isdir(project_path):
            logger.warning("Heartbeat: invalid project path: %s", project_path)
            return []

        self._status.last_tick = time.time()
        self._status.total_ticks += 1

        results = []

        # Available check implementations
        check_registry = {
            "unity_compile": lambda: unity_compile.run(project_path),
            "new_files": lambda: new_files.run(
                project_path,
                source_dir=self.config.source_dir,
                file_extensions=self.config.file_extensions,
            ),
            "todo_markers": lambda: todo_markers.run(
                project_path,
                source_dir=self.config.source_dir,
                file_extensions=self.config.file_extensions,
            ),
            "large_files": lambda: large_files.run(
                project_path,
                self.config.large_file_threshold,
                source_dir=self.config.source_dir,
                file_extensions=self.config.file_extensions,
            ),
        }

        # Include dynamically registered skill checks (wrapped with project_path)
        for check_name, run_fn in self._skill_checks.items():
            check_registry[check_name] = (lambda fn=run_fn: fn(project_path))

        # Only run checks that are in the config (plus all skill checks)
        config_names = set(self.config.checks) | set(self._skill_checks.keys())
        checks = [
            (name, check_registry[name])
            for name in config_names
            if name in check_registry
        ]

        for check_name, check_fn in checks:
            try:
                result = check_fn()
                results.append(result)
                if result.issues:
                    logger.info("Heartbeat [%s]: %s", check_name, result.summary)
            except Exception as e:
                logger.error("Heartbeat check '%s' crashed: %s", check_name, e)
                results.append(CheckResult(
                    check_name=check_name, ok=True,
                    summary=f"Check error: {e}",
                ))

        # Store results for API
        self._status.last_results = [
            {
                "check": r.check_name,
                "ok": r.ok,
                "issue_count": r.issue_count,
                "summary": r.summary,
            }
            for r in results
        ]

        # Auto-enqueue tasks for actionable issues
        self._auto_enqueue(results, project_path)

        # Save heartbeat state to disk
        self._save_state(project_path, results)

        return results

    def _auto_enqueue(self, results: list[CheckResult], project_path: str):
        """Auto-enqueue fix tasks for critical issues, respecting rate limits."""
        if not self._can_auto_enqueue():
            return

        for result in results:
            if not result.ok and result.issues and self.config.auto_fix_on_error:
                self._enqueue_auto_fix(result, project_path)

    def _can_auto_enqueue(self) -> bool:
        """Check rate limit: max N auto-tasks per hour."""
        now = time.time()
        hour_ago = now - 3600
        self._auto_task_times = [t for t in self._auto_task_times if t > hour_ago]
        return len(self._auto_task_times) < self.config.max_auto_tasks_per_hour

    def _enqueue_auto_fix(self, result: CheckResult, project_path: str):
        """Enqueue a task to fix issues found by a heartbeat check."""
        issues_summary = "\n".join(
            f"- {e.get('file', 'unknown')}({e.get('line', '?')}): "
            f"{e.get('code', '')} {e.get('message', e.get('text', ''))}"
            for e in result.issues[:10]
        )
        task_text = (
            f"Fix the following {len(result.issues)} issue(s) "
            f"detected by the '{result.check_name}' check:\n\n{issues_summary}\n\n"
            "Read each file, understand the issue, and fix it."
        )
        task_id = self.queue.enqueue(
            task_text=task_text,
            project_path=project_path,
            priority=10,
            task_type=TaskType.HEARTBEAT,
            metadata={"source": "heartbeat", "check": result.check_name},
        )
        self._auto_task_times.append(time.time())
        self._status.auto_tasks_enqueued += 1
        logger.info(
            "Auto-enqueued fix task #%d for check '%s' (%d issues)",
            task_id, result.check_name, len(result.issues),
        )

    def _save_state(self, project_path: str, results: list[CheckResult]):
        """Save heartbeat summary to HEARTBEAT.md in the data directory."""
        os.makedirs(_STATE_DIR, exist_ok=True)
        path = os.path.join(_STATE_DIR, "HEARTBEAT.md")

        lines = [
            f"# Heartbeat Status",
            f"",
            f"**Last check:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Project:** {project_path}",
            f"**Total ticks:** {self._status.total_ticks}",
            f"**Auto-tasks enqueued:** {self._status.auto_tasks_enqueued}",
            f"",
            f"## Check Results",
            f"",
        ]

        for r in results:
            icon = "OK" if r.ok else "ISSUE"
            lines.append(f"### [{icon}] {r.check_name}")
            lines.append(f"{r.summary}")
            if r.issues:
                for issue in r.issues[:5]:
                    lines.append(f"- {issue.get('file', 'unknown')}: {issue.get('message', issue.get('text', ''))}")
                if len(r.issues) > 5:
                    lines.append(f"- ... and {len(r.issues) - 5} more")
            lines.append("")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as e:
            logger.warning("Cannot write HEARTBEAT.md: %s", e)
