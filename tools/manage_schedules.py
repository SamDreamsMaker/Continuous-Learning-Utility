"""manage_schedules tool: lets the agent list, create, update, delete, and toggle schedules."""

import json
import logging

from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ManageSchedulesTool(BaseTool):

    def __init__(self):
        self._scheduler = None  # Wired by AgentRunner at init time

    @property
    def name(self) -> str:
        return "manage_schedules"

    @property
    def description(self) -> str:
        return (
            "Manage cron schedules (stored in config/schedules.yaml). "
            "Actions: list, create, update, delete, toggle.\n"
            "Cron format: 'minute hour day month weekday' (0=Mon..6=Sun).\n"
            "Each schedule fires a task_template from prompts/task_templates/automation/.\n"
            "Requires the daemon scheduler to be wired. If unavailable, "
            "edit config/schedules.yaml directly via write_file as a fallback."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "update", "delete", "toggle"],
                    "description": "The action to perform.",
                },
                "schedule_id": {
                    "type": "string",
                    "description": "Unique schedule ID (required for create/update/delete/toggle). Use a short snake_case name.",
                },
                "cron": {
                    "type": "string",
                    "description": "Cron expression, e.g. '0 */6 * * *' (required for create, optional for update).",
                },
                "task_template": {
                    "type": "string",
                    "description": "Template name, e.g. 'code_review' (required for create, optional for update).",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Whether the schedule is enabled (optional for create/update).",
                },
                "priority": {
                    "type": "integer",
                    "description": "Task priority (optional, default 0).",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description (optional).",
                },
            },
            "required": ["action"],
        }

    def execute(self, args: dict, project_path: str, sandbox, backup) -> dict:
        if self._scheduler is None:
            return {
                "error": "Scheduler not available (daemon not running or not wired).",
                "hint": "You can edit config/schedules.yaml directly using write_file to add or modify schedules. "
                        "The daemon will pick up changes on next restart.",
            }

        action = args.get("action", "")

        if action == "list":
            return self._list()
        elif action == "create":
            return self._create(args)
        elif action == "update":
            return self._update(args)
        elif action == "delete":
            return self._delete(args)
        elif action == "toggle":
            return self._toggle(args)
        else:
            return {"error": f"Unknown action: {action}. Use list/create/update/delete/toggle."}

    def _list(self) -> dict:
        status = self._scheduler.status
        return {
            "total": status["total_schedules"],
            "active": status["active_schedules"],
            "schedules": status["schedules"],
        }

    def _create(self, args: dict) -> dict:
        sid = args.get("schedule_id", "")
        cron = args.get("cron", "")
        template = args.get("task_template", "")

        if not sid:
            return {"error": "schedule_id is required for create. Provide a unique snake_case ID."}
        if not cron:
            return {"error": "cron is required for create"}
        if not template:
            return {"error": "task_template is required for create"}

        # Check for duplicate: same task_template + cron already exists
        existing = self._scheduler.status.get("schedules", [])
        for s in existing:
            if s.get("task_template") == template and s.get("cron") == cron:
                return {
                    "error": f"A schedule with the same task_template '{template}' and cron '{cron}' already exists (id='{s['id']}'). "
                             f"Use 'update' to modify it or 'delete' to remove it first.",
                }

        try:
            sched = self._scheduler.add_schedule(
                schedule_id=sid,
                cron=cron,
                task_template=template,
                enabled=args.get("enabled", True),
                priority=args.get("priority", 0),
                description=args.get("description", ""),
            )
            return {"ok": True, "schedule": sched.to_dict()}
        except (ValueError, Exception) as e:
            return {"error": str(e)}

    def _update(self, args: dict) -> dict:
        sid = args.get("schedule_id", "")
        if not sid:
            return {"error": "schedule_id is required for update"}

        kwargs = {}
        for key in ("cron", "task_template", "enabled", "priority", "description"):
            if key in args:
                kwargs[key] = args[key]

        if not kwargs:
            return {"error": "No fields to update"}

        try:
            sched = self._scheduler.update_schedule(sid, **kwargs)
            if not sched:
                return {"error": f"Schedule '{sid}' not found"}
            return {"ok": True, "schedule": sched.to_dict()}
        except Exception as e:
            return {"error": str(e)}

    def _delete(self, args: dict) -> dict:
        sid = args.get("schedule_id", "")
        if not sid:
            return {"error": "schedule_id is required for delete"}

        ok = self._scheduler.delete_schedule(sid)
        if not ok:
            return {"error": f"Schedule '{sid}' not found"}
        return {"ok": True, "deleted": sid}

    def _toggle(self, args: dict) -> dict:
        sid = args.get("schedule_id", "")
        if not sid:
            return {"error": "schedule_id is required for toggle"}

        sched = self._scheduler.get_schedule(sid)
        if not sched:
            return {"error": f"Schedule '{sid}' not found"}

        new_state = not sched.enabled
        self._scheduler.update_schedule(sid, enabled=new_state)
        return {"ok": True, "schedule_id": sid, "enabled": new_state}
