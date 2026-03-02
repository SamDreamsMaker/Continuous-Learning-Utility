"""Tool registry: maps tool names to their handlers and schemas."""

import importlib
import logging

from tools.base import BaseTool

logger = logging.getLogger(__name__)

# Maps tool name -> (module_path, class_name) for lazy loading
TOOL_MAP = {
    "think": ("tools.think", "ThinkTool"),
    "read_file": ("tools.read_file", "ReadFileTool"),
    "list_files": ("tools.list_files", "ListFilesTool"),
    "search_in_files": ("tools.search_in_files", "SearchInFilesTool"),
    "write_file": ("tools.write_file", "WriteFileTool"),
    "validate_csharp": ("tools.validate_csharp", "ValidateCSharpTool"),
    "unity_logs": ("tools.unity_logs", "UnityLogsTool"),
    "memory": ("tools.memory_tool", "MemoryTool"),
    "manage_schedules": ("tools.manage_schedules", "ManageSchedulesTool"),
    "manage_context": ("tools.manage_context", "ManageContextTool"),
}


class ToolRegistry:
    """
    Registry of all available tools.

    Provides:
    - Tool lookup by name
    - OpenAI-format schemas for all registered tools
    """

    # Base write-mode tools (framework-specific tools added dynamically)
    WRITE_MODE_TOOLS = ["think", "write_file", "memory", "delegate"]

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name, or None if not found."""
        return self._tools.get(name)

    @property
    def names(self) -> list[str]:
        """List of all registered tool names."""
        return list(self._tools.keys())

    @property
    def schemas(self) -> list[dict]:
        """All tool definitions in OpenAI function calling format."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def schemas_only(self, names: list[str]) -> list[dict]:
        """Get schemas for only the specified tool names."""
        return [
            tool.to_openai_schema()
            for name, tool in self._tools.items()
            if name in names
        ]

    def get_write_mode_tools(self) -> list[str]:
        """Return write-mode tool names, including any registered validation/log tools."""
        extra = []
        for name in ["validate_csharp", "unity_logs"]:
            if name in self._tools:
                extra.append(name)
        return self.WRITE_MODE_TOOLS + extra

    def register_all_defaults(self, enabled_tools: list[str] | None = None):
        """Register tools based on the enabled list. If None, register all from TOOL_MAP."""
        targets = enabled_tools if enabled_tools is not None else list(TOOL_MAP.keys())
        for tool_name in targets:
            if tool_name not in TOOL_MAP:
                continue
            module_path, class_name = TOOL_MAP[tool_name]
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self.register(cls())
            except (ImportError, AttributeError) as e:
                logger.debug("Skipping optional tool '%s': %s", tool_name, e)
