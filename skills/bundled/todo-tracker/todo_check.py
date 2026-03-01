"""TODO marker check for the todo-tracker skill."""

import os
import re

name = "todo_markers_skill"

_MARKER_RE = re.compile(
    r"(?://|#|--)\s*(TODO|FIXME|HACK|NOTE)\b[:\s]*(.*)",
    re.IGNORECASE,
)


def run(project_path: str, **kwargs) -> object:
    """Scan all text source files for TODO/FIXME/HACK markers."""
    from daemon.checks.base import CheckResult

    markers = []
    text_extensions = {
        ".py", ".js", ".ts", ".cs", ".java", ".go", ".rs", ".cpp", ".c",
        ".h", ".rb", ".php", ".swift", ".kt", ".lua", ".sh",
    }

    for root, dirs, files in os.walk(project_path):
        # Skip hidden and common non-source dirs
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d not in {"node_modules", "__pycache__", "venv", ".venv", "dist", "build"}
        ]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in text_extensions:
                continue
            full = os.path.join(root, fname)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        match = _MARKER_RE.search(line)
                        if match:
                            rel = os.path.relpath(full, project_path).replace("\\", "/")
                            markers.append({
                                "file": rel,
                                "line": line_num,
                                "marker": match.group(1).upper(),
                                "text": match.group(2).strip()[:120],
                            })
            except OSError:
                continue

    if markers:
        by_type = {}
        for m in markers:
            by_type[m["marker"]] = by_type.get(m["marker"], 0) + 1
        parts = [f"{count} {typ}" for typ, count in sorted(by_type.items())]
        return CheckResult(
            check_name=name,
            ok=True,
            issues=markers,
            summary=f"{len(markers)} marker(s): {', '.join(parts)}",
        )

    return CheckResult(check_name=name, ok=True, summary="No TODO/FIXME markers found")
