"""AgentDaemon: background process that polls the task queue and runs agent tasks.

Runs as a separate process from the web server. Communicates via shared SQLite DB.
"""

import asyncio
import logging
import os
import signal
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from daemon.task_queue import TaskQueue, TaskStatus, Task
from daemon.heartbeat import HeartbeatManager, HeartbeatConfig
from daemon.scheduler import TaskScheduler
from daemon.notifiers import NotificationManager
from orchestrator.config import AgentConfig, load_config
from orchestrator.providers.factory import create_provider
from orchestrator.runner import AgentRunner
from orchestrator.session import SessionManager
from orchestrator import events as evt
from skills.manager import SkillManager

logger = logging.getLogger(__name__)

# Default poll interval when queue is empty
DEFAULT_POLL_INTERVAL = 5  # seconds
_LAST_REGISTRY_SYNC_KEY = "_last_registry_sync"


class AgentDaemon:
    """Background daemon that consumes tasks from the queue.

    Lifecycle:
        daemon = AgentDaemon(config, queue)
        daemon.run()  # blocks until stopped
    """

    def __init__(
        self,
        config: AgentConfig,
        queue: TaskQueue | None = None,
        session_mgr: SessionManager | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        stale_timeout: int = 600,
        skill_manager: SkillManager | None = None,
        schedules_path: str | None = None,
    ):
        self.config = config
        self.queue = queue or TaskQueue()
        self.session_mgr = session_mgr or SessionManager()
        self.poll_interval = poll_interval
        self.stale_timeout = stale_timeout
        self.skill_manager = skill_manager or SkillManager.empty()

        self._running = False
        self._current_task: Task | None = None
        self._started_at: float | None = None
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._last_registry_sync: float = 0.0

        # Heartbeat
        hb_config = HeartbeatConfig(
            enabled=config.heartbeat_enabled,
            interval=config.heartbeat_interval,
            auto_fix_compile_errors=config.heartbeat_auto_fix_compile,
            auto_fix_on_error=config.heartbeat_auto_fix_on_error,
            max_auto_tasks_per_hour=config.heartbeat_max_auto_tasks,
            large_file_threshold=config.heartbeat_large_file_threshold,
            checks=config.heartbeat_checks,
            source_dir=config.project_source_dir.strip("/").strip("\\"),
            file_extensions=config.project_file_extensions,
        )
        self.heartbeat = HeartbeatManager(queue=self.queue, config=hb_config)
        self.heartbeat.register_skill_checks(self.skill_manager)
        self.scheduler = TaskScheduler(queue=self.queue, config_path=schedules_path)
        self.notifier = NotificationManager()
        self._project_path: str | None = None

    @property
    def status(self) -> dict:
        """Current daemon status for API/UI."""
        return {
            "running": self._running,
            "started_at": self._started_at,
            "uptime": time.time() - self._started_at if self._started_at else 0,
            "current_task": self._current_task.id if self._current_task else None,
            "tasks_completed": self._tasks_completed,
            "tasks_failed": self._tasks_failed,
            "poll_interval": self.poll_interval,
            "queue_stats": self.queue.stats(),
            "heartbeat": self.heartbeat.status,
            "scheduler": self.scheduler.status,
        }

    def run(self):
        """Main blocking entry point. Sets up signal handlers and runs the async loop."""
        self._running = True
        self._started_at = time.time()

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        logger.info("Daemon started (poll_interval=%.1fs)", self.poll_interval)

        try:
            asyncio.run(self._main_loop())
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            logger.info(
                "Daemon stopped (completed=%d, failed=%d)",
                self._tasks_completed, self._tasks_failed,
            )

    async def _main_loop(self):
        """Async main loop: cleanup stale → poll → execute → sleep."""
        # Recover any tasks stuck from a previous crash
        stale = self.queue.cleanup_stale(self.stale_timeout)
        if stale:
            logger.info("Recovered %d stale tasks on startup", stale)

        while self._running:
            task = self.queue.dequeue()

            if task:
                # Track project path from tasks for heartbeat
                project = task.payload.get("project")
                if project:
                    self._project_path = project
                await self._execute_task(task)
            else:
                # Queue empty — run heartbeat if it's time
                if self._project_path and self.heartbeat.should_tick():
                    logger.info("Heartbeat tick (project: %s)", self._project_path)
                    self.heartbeat.tick(self._project_path)

                # Run scheduler if it's time
                if self._project_path and self.scheduler.should_tick():
                    enqueued = self.scheduler.tick(self._project_path)
                    if enqueued:
                        logger.info("Scheduler enqueued %d tasks", len(enqueued))
                        continue  # Process newly enqueued tasks immediately

                # Run registry sync if enabled and due
                await self._maybe_sync_registry()

                await asyncio.sleep(self.poll_interval)

    async def _execute_task(self, task: Task):
        """Run a single task via AgentRunner."""
        self._current_task = task
        payload = task.payload
        task_text = payload.get("task", "")
        project_path = payload.get("project", "")
        role = task.metadata.get("role")  # Optional role from delegation

        logger.info("Executing task #%d: %s (role=%s)", task.id, task_text[:80], role or "default")

        if not project_path or not os.path.isdir(project_path):
            self.queue.fail(task.id, f"Invalid project path: {project_path}")
            self._tasks_failed += 1
            self._current_task = None
            return

        try:
            provider = create_provider(
                self.config.provider, self.config.api_base,
                self.config.api_key, self.config.model,
            )
            runner = AgentRunner(
                config=self.config,
                provider=provider,
                project_path=project_path,
                session_mgr=self.session_mgr,
                role=role,
                task_queue=self.queue,
                scheduler=self.scheduler,
                skill_manager=self.skill_manager,
            )

            result = await runner.run(task=task_text)

            if result.success:
                self.queue.complete(task.id, result={
                    "response": result.response,
                    "iterations": result.iterations,
                    "tokens": result.tokens,
                    "session_id": result.session_id,
                    "files_modified": [f["relative"] for f in result.files_modified],
                })
                self._tasks_completed += 1
                logger.info("Task #%d completed (iter=%d, tokens=%d)",
                            task.id, result.iterations, result.tokens)
                self.notifier.notify(
                    f"Task #{task.id} completed",
                    f"{task_text[:80]} — {result.iterations} iterations",
                    "info",
                )
            else:
                self.queue.fail(task.id, result.error or "Unknown error")
                self._tasks_failed += 1
                self.notifier.notify(
                    f"Task #{task.id} failed",
                    result.error or "Unknown error",
                    "error",
                )

        except Exception as e:
            logger.exception("Task #%d crashed: %s", task.id, e)
            self.queue.fail(task.id, str(e))
            self._tasks_failed += 1
            self.notifier.notify(f"Task #{task.id} crashed", str(e)[:200], "error")
        finally:
            self._current_task = None

    async def _maybe_sync_registry(self) -> None:
        """Sync community registry skills if enabled and the interval has elapsed."""
        if not self.config.skills_registry_sync_enabled:
            return
        now = time.time()
        if now - self._last_registry_sync < self.config.skills_registry_sync_interval:
            return
        self._last_registry_sync = now
        logger.info("Registry sync starting (interval=%ds)", self.config.skills_registry_sync_interval)
        try:
            from skills.registry import sync as registry_sync
            result = await asyncio.to_thread(
                registry_sync,
                self.config.skills_registry_url,
                None,  # use default cache dir
                lambda: setattr(self, "skill_manager", None),  # invalidate (daemon re-creates on next task)
            )
            if result.changed:
                logger.info(
                    "Registry sync: +%d added, ~%d updated, %d skipped",
                    len(result.added), len(result.updated), len(result.skipped),
                )
        except Exception as e:
            logger.error("Registry sync failed: %s", e)

    def stop(self):
        """Signal the daemon to stop after current task completes."""
        logger.info("Daemon stop requested")
        self._running = False

    def _handle_signal(self, signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False


def main():
    """CLI entry point for running the daemon directly."""
    import argparse

    parser = argparse.ArgumentParser(description="CLU Daemon")
    parser.add_argument("--config", default="config/default.yaml", help="Config file")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL,
                        help="Seconds between queue polls (default: 5)")
    parser.add_argument("--project", help="Project path (for heartbeat/scheduler)")
    parser.add_argument("--schedules", default="config/schedules.yaml",
                        help="Schedules config file")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(os.path.dirname(__file__), "..", "logs", "daemon.log"),
                encoding="utf-8",
            ),
        ],
    )

    # Load config
    agent_dir = os.path.join(os.path.dirname(__file__), "..")
    config_path = os.path.join(agent_dir, args.config)
    load_config(config_path)
    config = AgentConfig.from_yaml(config_path)

    print(f"CLU Daemon")
    print(f"  Provider: {config.provider} / {config.model}")
    print(f"  Poll interval: {args.poll_interval}s")
    print(f"  Heartbeat: {'ON' if config.heartbeat_enabled else 'OFF'}"
          f" (every {config.heartbeat_interval}s)")
    print(f"  Schedules: {args.schedules}")
    if args.project:
        print(f"  Project: {args.project}")
    print(f"  Press Ctrl+C to stop\n")

    sched_path = os.path.join(agent_dir, args.schedules)
    daemon = AgentDaemon(
        config=config,
        poll_interval=args.poll_interval,
        schedules_path=sched_path if os.path.isfile(sched_path) else None,
    )
    print(f"  Loaded {len(daemon.scheduler.schedules)} schedules")
    # Load notification channels from config
    import yaml
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}
        notif_config = raw_config.get("notifications", {})
        daemon.notifier = NotificationManager.from_config(notif_config)
        if daemon.notifier.channels:
            print(f"  Notifications: {', '.join(daemon.notifier.channels)}")
    except Exception as e:
        logger.warning("Failed to load notification config: %s", e)
    if args.project:
        daemon._project_path = args.project
    daemon.run()


if __name__ == "__main__":
    main()
