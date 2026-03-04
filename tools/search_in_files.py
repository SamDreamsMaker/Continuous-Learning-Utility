"""search_in_files tool: searches for regex patterns across files."""

import os
import re
import glob as glob_module

from tools.base import BaseTool
from orchestrator.exceptions import SandboxViolation


class SearchInFilesTool(BaseTool):

    MAX_RESULTS_CAP = 50

    @property
    def name(self) -> str:
        return "search_in_files"

    @property
    def description(self) -> str:
        return (
            "Search for a text or Python regex pattern across project files (max 50 results). "
            "Returns [{file, line, match, context}] with ~2 lines of context per match. "
            "Use file_pattern to filter by extension (e.g. '*.py'). "
            "Path defaults to project root. Regex uses Python `re` module syntax."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (supports regex).",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (relative to project root).",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern for files to search (e.g., '*.py', '*.cs'). Default: all files.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matches to return. Default: 20.",
                },
            },
            "required": ["pattern"],
        }

    def execute(self, args: dict, project_path: str, sandbox, backup) -> dict:
        pattern = args.get("pattern", "")
        path = args.get("path", "")
        file_pattern = args.get("file_pattern", "*")
        max_results = min(args.get("max_results", 20), self.MAX_RESULTS_CAP)

        full_path = os.path.join(project_path, path)

        try:
            sandbox.validate(full_path, project_path)
        except SandboxViolation as e:
            return {"error": str(e)}

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        glob_path = os.path.join(full_path, "**", file_pattern)
        matches = []

        for filepath in glob_module.glob(glob_path, recursive=True):
            if len(matches) >= max_results:
                break
            if not os.path.isfile(filepath):
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except (UnicodeDecodeError, PermissionError):
                continue

            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    rel = os.path.relpath(filepath, project_path).replace("\\", "/")
                    context_start = max(0, line_num - 2)
                    context_end = min(len(lines), line_num + 1)
                    context = "".join(lines[context_start:context_end]).rstrip()

                    matches.append({
                        "file": rel,
                        "line": line_num,
                        "match": line.strip(),
                        "context": context,
                    })
                    if len(matches) >= max_results:
                        break

        return {
            "pattern": pattern,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
        }
