"""list_files tool: lists files in a directory with optional glob filtering."""

import os
import glob as glob_module

from tools.base import BaseTool
from orchestrator.exceptions import SandboxViolation


class ListFilesTool(BaseTool):

    MAX_RESULTS = 200

    @property
    def name(self) -> str:
        return "list_files"

    @property
    def description(self) -> str:
        return (
            "List files in a directory (max 200 results). "
            "Supports glob patterns (*, **, ?) via the 'pattern' param. "
            "Returns [{path, size}] sorted alphabetically. "
            "Path defaults to project root. Set recursive=true for subdirectories."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path within the project source directory.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.cs'). Default: '*'.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to list files recursively. Default: false.",
                },
            },
        }

    def execute(self, args: dict, project_path: str, sandbox, backup) -> dict:
        path = args.get("path", "")
        pattern = args.get("pattern", "*")
        recursive = args.get("recursive", False)

        full_path = os.path.join(project_path, path)

        try:
            sandbox.validate(full_path, project_path)
        except SandboxViolation as e:
            return {"error": str(e)}

        if not os.path.isdir(full_path):
            return {"error": f"Directory not found: {path}"}

        if recursive:
            glob_pattern = os.path.join(full_path, "**", pattern)
        else:
            glob_pattern = os.path.join(full_path, pattern)

        files = glob_module.glob(glob_pattern, recursive=recursive)

        entries = []
        for f in sorted(files)[: self.MAX_RESULTS]:
            if os.path.isfile(f):
                rel = os.path.relpath(f, project_path).replace("\\", "/")
                entries.append({
                    "path": rel,
                    "size": os.path.getsize(f),
                })

        return {
            "directory": path,
            "count": len(entries),
            "truncated": len(files) > self.MAX_RESULTS,
            "files": entries,
        }
