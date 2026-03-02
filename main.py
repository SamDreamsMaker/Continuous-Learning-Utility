"""
CLU (Continuous Learning Utility) - Entry Point

Usage:
    python main.py --project "D:/PROJECTS/MyProject" --task "Refactor PlayerController for SRP"
    python main.py --project "D:/PROJECTS/MyProject" --task-file tasks/my_task.md
    python main.py --project "D:/PROJECTS/MyProject" --interactive
    python main.py --project "D:/PROJECTS/MyProject" --web
    python main.py --project "D:/PROJECTS/MyProject" --rollback
    python main.py --daemon start
    python main.py --daemon stop
    python main.py --daemon status
"""

import argparse
import logging
import os
import sys

from orchestrator.config import AgentConfig, load_config
from orchestrator.agent import Agent


def setup_logging(log_dir: str, verbose: bool = False):
    """Configure logging to file and console."""
    os.makedirs(log_dir, exist_ok=True)

    from datetime import datetime
    log_file = os.path.join(log_dir, f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    handlers = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    return log_file


def run_single_task(agent: Agent, task: str, project_path: str):
    """Run a single task and print results."""
    result = agent.run(task, project_path)

    print(f"\n{'=' * 60}")
    print(f"Agent finished: {'SUCCESS' if result.success else 'FAILED'}")
    print(f"Iterations: {agent.budget.iteration}/{agent.budget.max_iterations}")
    print(f"Tokens used: {agent.budget.total_tokens}/{agent.budget.max_total_tokens}")

    if result.files_modified:
        print(f"Files modified: {len(result.files_modified)}")
        for f in result.files_modified:
            print(f"  - {f['relative']}")

    if result.error:
        print(f"Error: {result.error}")

    print(f"{'=' * 60}")

    if result.response:
        print(f"\nAgent summary:\n{result.response}")

    return result


def run_interactive(config: AgentConfig, project_path: str):
    """REPL-style interactive mode."""
    print("CLU - Interactive Mode")
    print("Commands: 'quit' to exit, 'rollback' to undo last changes, 'status' for budget info")
    print(f"Project: {project_path}")
    print(f"Model: {config.model}")
    print()

    agent = Agent(config)

    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not task:
            continue
        if task.lower() == "quit":
            break
        if task.lower() == "rollback":
            count = agent.backup.rollback()
            print(f"Rolled back {count} file(s).")
            continue
        if task.lower() == "status":
            print(f"Budget: {agent.budget.status()}")
            print(f"Files modified: {len(agent.backup.modified_files)}")
            continue

        # Create a fresh agent for each task to reset budget
        agent = Agent(config)
        run_single_task(agent, task, project_path)


def _run_skills_command(command: str, config_path: str, project_path: str | None):
    """Execute a skills CLI command."""
    from orchestrator.config import AgentConfig
    from skills.loader import SkillLoader
    from skills.manager import SkillManager

    # Load config for skills settings
    try:
        config = AgentConfig.from_yaml(config_path)
    except Exception:
        config = AgentConfig()

    if not config.skills_enabled:
        print("Skills are disabled in config (skills.enabled=false).")
        return

    # Resolve project-local skills dir
    proj_skills_dir = None
    if project_path and config.skills_project_dir:
        proj_skills_dir = os.path.join(project_path, config.skills_project_dir)
    elif project_path:
        candidate = os.path.join(project_path, ".clu", "skills")
        if os.path.isdir(candidate):
            proj_skills_dir = candidate

    loader = SkillLoader(
        user_skills_dir=config.skills_user_dir or None,
        project_skills_dir=proj_skills_dir,
    )
    manager = SkillManager.from_loader(loader)

    if command == "list":
        if manager.skill_count == 0:
            print("No skills loaded.")
            return
        print(f"Loaded skills ({manager.skill_count}):\n")
        for item in manager.summary():
            tier_tag = f"[{item['tier']}]"
            tools_str = ", ".join(item["tools"]) if item["tools"] else "none"
            print(f"  {item['name']} v{item['version']} {tier_tag}")
            print(f"    {item['description'] or '(no description)'}")
            print(f"    Tools: {tools_str}")
            if item["tags"]:
                print(f"    Tags:  {', '.join(item['tags'])}")
            print()

    elif command == "test":
        from skills.test_runner import SkillTestRunner

        runner = SkillTestRunner(project_path=project_path or os.getcwd())
        reports = runner.run_skills(manager.skills)

        if not reports:
            print("No skills with test cases found.")
            return

        total_passed = total_failed = 0
        for report in reports:
            total_passed += report.passed
            total_failed += report.failed
            status = "PASS" if report.success else "FAIL"
            print(f"[{status}] {report.skill_name}: {report.passed}/{report.total} passed")
            for r in report.results:
                icon = "  OK " if r.passed else "  FAIL"
                line = f"{icon}  {r.test_name} ({r.duration_ms:.0f}ms)"
                if not r.passed and r.error:
                    line += f" — {r.error}"
                print(line)
            print()

        print(f"Results: {total_passed} passed, {total_failed} failed")
        if total_failed > 0:
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="CLU — Continuous Learning Utility"
    )
    parser.add_argument(
        "--project",
        help="Path to Unity project root (required for CLI modes, optional for --web)",
    )
    parser.add_argument(
        "--task",
        help="Task description string",
    )
    parser.add_argument(
        "--task-file",
        help="Path to a file containing the task description",
    )
    parser.add_argument(
        "--config", default="config/default.yaml",
        help="Path to config YAML file (default: config/default.yaml)",
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Interactive mode: enter tasks one by one",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="Launch the web dashboard (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Port for the web dashboard (default: 8080)",
    )
    parser.add_argument(
        "--rollback", action="store_true",
        help="Rollback the most recent session's changes",
    )
    parser.add_argument(
        "--daemon",
        choices=["start", "stop", "status"],
        help="Manage the background daemon: start, stop, or check status",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print logs to console in addition to log file",
    )
    parser.add_argument(
        "--skills",
        choices=["list", "test"],
        metavar="COMMAND",
        help="Skills commands: 'list' to show loaded skills, 'test' to run skill tests",
    )
    parser.add_argument(
        "--secret",
        nargs="+",
        metavar="ARG",
        help="Manage secrets: set <name> <value>, get <name>, delete <name>, list",
    )

    args = parser.parse_args()

    # Resolve paths
    agent_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(agent_dir, args.config) if not os.path.isabs(args.config) else args.config
    project_path = os.path.abspath(args.project) if args.project else None

    # Secret management (no project required)
    if args.secret:
        from orchestrator.secrets import get_secret, set_secret, delete_secret, list_secrets
        action = args.secret[0]
        if action == "set" and len(args.secret) >= 3:
            set_secret(args.secret[1], args.secret[2])
            print(f"Secret '{args.secret[1]}' stored in OS keyring.")
        elif action == "get" and len(args.secret) >= 2:
            val = get_secret(args.secret[1])
            if val:
                masked = "****" + val[-4:] if len(val) > 4 else "****"
                print(f"{args.secret[1]}: {masked}")
            else:
                print(f"{args.secret[1]}: (not set)")
        elif action == "delete" and len(args.secret) >= 2:
            delete_secret(args.secret[1])
            print(f"Secret '{args.secret[1]}' removed.")
        elif action == "list":
            stored = list_secrets()
            if stored:
                for name in stored:
                    print(f"  {name}: stored in keyring")
            else:
                print("  No secrets stored in keyring.")
        else:
            print("Usage: --secret set <name> <value> | get <name> | delete <name> | list")
        return

    # Skills commands (no project required)
    if args.skills:
        _run_skills_command(args.skills, config_path, args.project)
        return

    # Daemon management (no project required)
    if args.daemon:
        from daemon import service as daemon_service
        if args.daemon == "start":
            result = daemon_service.start(
                config_path=args.config,
                verbose=args.verbose,
            )
            if result["ok"]:
                print(f"Daemon started (PID {result['pid']})")
            else:
                print(f"Error: {result['error']}")
                sys.exit(1)
        elif args.daemon == "stop":
            result = daemon_service.stop()
            if result["ok"]:
                print("Daemon stopped")
            else:
                print(f"Error: {result['error']}")
                sys.exit(1)
        elif args.daemon == "status":
            result = daemon_service.status()
            if result["running"]:
                print(f"Daemon is running (PID {result['pid']})")
            else:
                print("Daemon is not running")
        return

    # Web mode can work without a project (set from UI)
    if args.web:
        load_config(config_path)
        log_dir = os.path.join(agent_dir, "logs")
        setup_logging(log_dir, verbose=args.verbose)
        from web.server import start_server
        start_server(project_path=project_path, port=args.port)
        return

    # CLI modes require a project
    if not project_path:
        parser.error("--project is required for CLI modes (use --web for the dashboard)")

    # Validate project path
    if not os.path.isdir(project_path):
        print(f"Error: Project directory not found: {project_path}")
        sys.exit(1)

    # Load config
    load_config(config_path)
    config = AgentConfig.from_yaml(config_path)

    source_dir = config.project_source_dir.strip("/").strip("\\")
    source_path = os.path.join(project_path, source_dir)
    if not os.path.isdir(source_path):
        print(f"Warning: No {source_dir}/ directory found in {project_path}.")

    # Setup logging
    log_dir = os.path.join(agent_dir, config.log_dir)
    log_file = setup_logging(log_dir, verbose=args.verbose)
    print(f"Logging to: {log_file}")

    # Test LLM provider connection
    from orchestrator.providers.factory import create_provider
    try:
        provider = create_provider(config.provider, config.api_base, config.api_key, config.model)
        result = provider.test_connection()
        if not result.get("ok"):
            print(f"Error: Cannot connect to {config.provider} at {config.api_base}")
            print(f"Details: {result.get('error', 'unknown')}")
            sys.exit(1)
        print(f"Connected to {provider.provider_name} ({config.model})")
    except Exception as e:
        print(f"Error: Provider initialization failed: {e}")
        sys.exit(1)

    # Handle modes
    if args.interactive:
        run_interactive(config, project_path)
        return

    if args.rollback:
        agent = Agent(config)
        count = agent.backup.rollback()
        print(f"Rolled back {count} file(s).")
        return

    # Get task
    task = None
    if args.task:
        task = args.task
    elif args.task_file:
        task_file = os.path.abspath(args.task_file)
        if not os.path.isfile(task_file):
            print(f"Error: Task file not found: {task_file}")
            sys.exit(1)
        with open(task_file, "r", encoding="utf-8") as f:
            task = f.read()
    else:
        parser.error("Must provide --task, --task-file, or --interactive")

    # Run
    agent = Agent(config)
    run_single_task(agent, task, project_path)


if __name__ == "__main__":
    main()
