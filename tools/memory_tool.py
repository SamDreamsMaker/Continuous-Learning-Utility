"""Memory tool: lets the agent read/write persistent knowledge and log observations."""

from tools.base import BaseTool
from orchestrator.memory import MemoryManager, CATEGORIES


class MemoryTool(BaseTool):

    def __init__(self):
        self._memory = MemoryManager()

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Read or write persistent memory stored in .clu/memory/.\n"
            "Actions:\n"
            "- read: Read a category → returns full text\n"
            "- write: Overwrite a category (replaces all content)\n"
            "- append: Add a line to a category (preserves existing)\n"
            "- log: Log an observation to today's activity log\n"
            "- today: Read today's activity log\n"
            f"Categories: {', '.join(CATEGORIES)}. "
            "Use 'append' to accumulate findings; 'write' only to reset a category."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write", "append", "log", "today"],
                    "description": "The memory action to perform",
                },
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "description": "Knowledge category (for read/write/append actions)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write/append/log",
                },
            },
            "required": ["action"],
        }

    def execute(self, args: dict, project_path: str, sandbox, backup) -> dict:
        action = args.get("action", "")
        category = args.get("category", "")
        content = args.get("content", "")

        if action == "read":
            if not category:
                return {"error": f"Category required. Available: {', '.join(CATEGORIES)}"}
            text = self._memory.read_knowledge(category)
            return {"category": category, "content": text or "(empty)"}

        elif action == "write":
            if not category:
                return {"error": f"Category required. Available: {', '.join(CATEGORIES)}"}
            if not content:
                return {"error": "Content required for write action"}
            ok = self._memory.write_knowledge(category, content)
            return {"ok": ok, "category": category}

        elif action == "append":
            if not category:
                return {"error": f"Category required. Available: {', '.join(CATEGORIES)}"}
            if not content:
                return {"error": "Content required for append action"}
            ok = self._memory.append_knowledge(category, content)
            return {"ok": ok, "category": category}

        elif action == "log":
            if not content:
                return {"error": "Content required for log action"}
            self._memory.log_activity(
                task="agent_observation",
                result_summary=content,
            )
            return {"ok": True, "logged": content[:100]}

        elif action == "today":
            text = self._memory.get_daily_log()
            return {"content": text or "(no activity today)"}

        else:
            return {"error": f"Unknown action: {action}. Use: read, write, append, log, today"}
