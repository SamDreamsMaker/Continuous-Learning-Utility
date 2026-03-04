"""write_file tool: writes or patches files with optional validation and backup."""

import os

from tools.base import BaseTool
from orchestrator.exceptions import SandboxViolation


class WriteFileTool(BaseTool):

    MAX_WRITE_SIZE = 50_000  # 50KB

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write or patch a file (max 50KB). Two modes:\n"
            "- 'content': full file content (creates or overwrites)\n"
            "- 'patches': array of incremental edits on existing file. Each patch has: "
            "action (replace|insert_after|insert_before|delete), target (exact string to find), "
            "replacement (new text). Patches apply in order.\n"
            "Existing files are backed up automatically. "
            "Respects sandbox: write-blocked prefixes (.clu, config) cannot be written."
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the project source directory.",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content for new files. Mutually exclusive with 'patches'.",
                },
                "patches": {
                    "type": "array",
                    "description": "Array of patches for incremental edits. Mutually exclusive with 'content'.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["replace", "insert_after", "insert_before", "delete"],
                            },
                            "target": {
                                "type": "string",
                                "description": "Exact string to find in the file.",
                            },
                            "replacement": {
                                "type": "string",
                                "description": "New content (for replace, insert_after, insert_before).",
                            },
                        },
                        "required": ["action", "target"],
                    },
                },
            },
            "required": ["path"],
        }

    def execute(self, args: dict, project_path: str, sandbox, backup) -> dict:
        path = args.get("path", "")
        full_path = os.path.join(project_path, path)

        try:
            sandbox.validate(full_path, project_path, mode="write")
        except SandboxViolation as e:
            return {"error": str(e)}

        content = args.get("content")
        patches = args.get("patches")

        if content and patches:
            return {"error": "Provide either 'content' or 'patches', not both."}
        if not content and not patches:
            return {"error": "Must provide 'content' or 'patches'."}

        if patches:
            return self._apply_patches(full_path, path, patches, project_path, sandbox, backup)
        else:
            return self._write_full(full_path, path, content, project_path, backup)

    def _write_full(self, full_path: str, rel_path: str, content: str, project_path: str, backup) -> dict:
        """Write a new file or overwrite completely."""
        # Check for null bytes (binary content)
        if "\x00" in content:
            return {"error": "Cannot write binary content"}

        if len(content.encode("utf-8")) > self.MAX_WRITE_SIZE:
            return {"error": f"Content exceeds {self.MAX_WRITE_SIZE} bytes limit"}

        # Validate C# before writing
        if rel_path.endswith(".cs"):
            validation = self._validate_csharp(content, project_path)
            if not validation["valid"]:
                return {
                    "error": "C# validation failed",
                    "details": validation["errors"],
                }

        # Backup existing file
        if os.path.isfile(full_path):
            backup.backup(full_path, project_path)

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

        return {
            "success": True,
            "path": rel_path,
            "bytes_written": len(content.encode("utf-8")),
        }

    def _apply_patches(self, full_path: str, rel_path: str, patches: list, project_path: str, sandbox, backup) -> dict:
        """Apply incremental patches to an existing file."""
        if not os.path.isfile(full_path):
            return {"error": f"Cannot patch non-existent file: {rel_path}"}

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                original = f.read()
        except UnicodeDecodeError:
            return {"error": f"Cannot read binary file: {rel_path}"}

        modified = original
        for i, patch in enumerate(patches):
            action = patch.get("action", "")
            target = patch.get("target", "")

            if not target:
                return {"error": f"Patch {i}: empty target string"}

            if target not in modified:
                return {
                    "error": f"Patch {i}: target string not found in file",
                    "target_preview": target[:200],
                }

            if action == "replace":
                replacement = patch.get("replacement", "")
                modified = modified.replace(target, replacement, 1)
            elif action == "insert_after":
                replacement = patch.get("replacement", "")
                idx = modified.index(target) + len(target)
                modified = modified[:idx] + "\n" + replacement + modified[idx:]
            elif action == "insert_before":
                replacement = patch.get("replacement", "")
                idx = modified.index(target)
                modified = modified[:idx] + replacement + "\n" + modified[idx:]
            elif action == "delete":
                modified = modified.replace(target, "", 1)
            else:
                return {"error": f"Patch {i}: unknown action '{action}'"}

        # Validate C# after all patches
        if rel_path.endswith(".cs"):
            validation = self._validate_csharp(modified, project_path)
            if not validation["valid"]:
                return {
                    "error": "C# validation failed after patching",
                    "details": validation["errors"],
                }

        # Backup and write
        backup.backup(full_path, project_path)

        with open(full_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(modified)

        return {
            "success": True,
            "path": rel_path,
            "patches_applied": len(patches),
        }

    @staticmethod
    def _validate_csharp(code: str, project_path: str) -> dict:
        """Validate C# code using the CSharpValidator, if available."""
        try:
            from validation.csharp_validator import CSharpValidator
        except ImportError:
            return {"valid": True}  # Validation not available, skip

        if not hasattr(WriteFileTool, "_validator_instance"):
            # Read unity_dll_path from config if available, else empty string
            from orchestrator.config import AgentConfig
            try:
                cfg = AgentConfig.load()
                dll_path = cfg.unity_dll_path or ""
            except Exception:
                dll_path = ""
            WriteFileTool._validator_instance = CSharpValidator(
                unity_dll_path=dll_path,
            )
        return WriteFileTool._validator_instance.validate(code, project_path)
