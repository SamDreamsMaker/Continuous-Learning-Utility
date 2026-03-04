"""Tool dispatcher: validates and executes tool calls."""

import json
import logging

from orchestrator.exceptions import SandboxViolation, ToolExecutionError

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches tool calls from the LLM to the appropriate handler."""

    def __init__(self, registry, sandbox, backup):
        self.registry = registry
        self.sandbox = sandbox
        self.backup = backup

    def dispatch(self, tool_call: dict, project_path: str) -> str:
        """
        Validate and execute a tool call.

        Args:
            tool_call: Normalized dict with keys: id, name, arguments.
            project_path: Absolute path to the project root.

        Returns:
            JSON-serialized result string for the LLM.
        """
        name = tool_call["name"]

        # Parse arguments
        try:
            args = json.loads(tool_call["arguments"])
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in tool arguments: %s", e)
            return json.dumps({
                "error": f"Invalid JSON in tool arguments: {e}",
                "raw": tool_call["arguments"][:500],
            })

        # Get handler
        handler = self.registry.get(name)
        if handler is None:
            logger.warning("Unknown tool called: %s", name)
            return json.dumps({
                "error": f"Unknown tool: {name}",
                "available_tools": self.registry.names,
            })

        # Execute
        try:
            logger.info("Executing tool: %s(%s)", name, json.dumps(args)[:200])
            result = handler.execute(args, project_path, self.sandbox, self.backup)
            logger.info("Tool %s returned: %s", name, json.dumps(result)[:200])
            return json.dumps(result)
        except SandboxViolation as e:
            logger.warning("Sandbox violation in %s: %s", name, e)
            return json.dumps({"error": f"Sandbox violation: {e}"})
        except ToolExecutionError as e:
            logger.error("Tool execution error in %s: %s", name, e)
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("Unexpected error in tool %s", name)
            return json.dumps({"error": f"Internal error: {type(e).__name__}: {e}"})
