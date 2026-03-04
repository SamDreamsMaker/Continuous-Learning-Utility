"""manage_context tool: lets the agent list, add, disable, and delete persistent context rules."""

import logging

from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ManageContextTool(BaseTool):

    def __init__(self):
        self._context_store = None  # Wired by AgentRunner._setup_context_tool()

    @property
    def name(self) -> str:
        return "manage_context"

    @property
    def description(self) -> str:
        return (
            "Manage persistent context rules (stored in .clu/user-context.json). "
            "Rules are injected into the agent system prompt on every run.\n"
            "Actions: list, add, disable, delete.\n"
            "Scopes: 'always' (injected in every run), 'coder'/'reviewer'/'tester' (only for that role).\n"
            "Use this to persist conventions, constraints, or coding standards the agent should always follow."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "disable", "delete"],
                    "description": "Action to perform.",
                },
                "name": {
                    "type": "string",
                    "description": "Rule name. Required for add, disable, delete.",
                },
                "content": {
                    "type": "string",
                    "description": "Rule text/instructions. Required for add.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["always", "coder", "reviewer", "tester"],
                    "description": (
                        "When to inject this rule. 'always' = every run (default). "
                        "'coder'/'reviewer'/'tester' = only for that agent role."
                    ),
                },
            },
            "required": ["action"],
        }

    def execute(self, args: dict, project_path: str, sandbox=None, backup=None) -> str:
        if self._context_store is None:
            return "Error: context store is not available."

        action = args.get("action", "").strip()

        if action == "list":
            return self._list()
        elif action == "add":
            return self._add(args)
        elif action == "disable":
            return self._disable(args)
        elif action == "delete":
            return self._delete(args)
        else:
            return f"Unknown action '{action}'. Valid actions: list, add, disable, delete."

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _list(self) -> str:
        items = self._context_store.list_items()
        if not items:
            return "No context rules defined."
        lines = ["Context rules:"]
        for item in items:
            status = "active" if item.enabled else "disabled"
            scope_label = f"[{item.scope}]" if item.scope != "always" else "[always]"
            lines.append(f"  - {item.name} {scope_label} ({status}): {item.content[:80]}{'...' if len(item.content) > 80 else ''}")
        return "\n".join(lines)

    def _add(self, args: dict) -> str:
        name = (args.get("name") or "").strip()
        content = (args.get("content") or "").strip()
        scope = (args.get("scope") or "always").strip()

        if not name:
            return "Error: 'name' is required for action 'add'."
        if not content:
            return "Error: 'content' is required for action 'add'."

        item = self._context_store.add_item(name=name, content=content, scope=scope)
        return f"Context rule added: '{item.name}' (scope={item.scope}, id={item.id})"

    def _disable(self, args: dict) -> str:
        name = (args.get("name") or "").strip()
        if not name:
            return "Error: 'name' is required for action 'disable'."

        item = self._context_store.get_item_by_name(name)
        if item is None:
            return f"No context rule found with name '{name}'."
        if not item.enabled:
            return f"Context rule '{name}' is already disabled."

        self._context_store.update_item(item.id, enabled=False)
        return f"Context rule '{name}' disabled."

    def _delete(self, args: dict) -> str:
        name = (args.get("name") or "").strip()
        if not name:
            return "Error: 'name' is required for action 'delete'."

        item = self._context_store.get_item_by_name(name)
        if item is None:
            return f"No context rule found with name '{name}'."

        self._context_store.delete_item(item.id)
        return f"Context rule '{name}' deleted."
