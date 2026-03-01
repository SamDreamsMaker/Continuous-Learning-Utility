"""Outcome tracker — appends structured task outcome data to data/outcomes.jsonl.

Each completed agent task writes one JSON line capturing keywords, tools used,
files touched, token/iteration metrics, and success status. The pattern analyzer
reads this file to discover recurring patterns and generate new skills.
"""

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

# Tech-relevant terms worth tracking as keywords
_TECH_TERMS: frozenset[str] = frozenset({
    # Languages
    "python", "javascript", "typescript", "csharp", "java", "golang", "rust",
    "cpp", "swift", "kotlin", "lua", "ruby", "php", "bash", "shell",
    # Unity / game dev
    "unity", "unreal", "godot", "monobehaviour", "gameobject", "prefab", "scene",
    "serializedfield", "inspector", "coroutine", "animation", "animator",
    "rigidbody", "collider", "physics", "shader", "material", "texture",
    "camera", "canvas", "navmesh", "pathfinding", "scriptableobject",
    "addressable", "assetbundle", "instantiate", "destroy", "raycast",
    # Common dev topics
    "api", "database", "sql", "rest", "graphql", "http", "websocket",
    "auth", "authentication", "login", "oauth", "jwt", "token",
    "test", "unittest", "mock", "fixture", "coverage", "assertion",
    "docker", "kubernetes", "ci", "deploy", "pipeline", "github", "git",
    "refactor", "cleanup", "lint", "format", "style", "convention",
    "performance", "optimization", "cache", "memory", "leak", "profiling",
    "bug", "fix", "error", "exception", "crash", "debug", "logging",
    "config", "settings", "environment", "variable",
    "todo", "fixme", "hack", "comment", "documentation",
    # File types as keywords
    "json", "yaml", "xml", "html", "css", "shader", "glsl",
})

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "my", "your", "our",
    "their", "i", "we", "you", "he", "she", "they", "all", "any", "some",
    "not", "no", "up", "out", "if", "so", "then", "than", "too", "very",
    "just", "make", "using", "use", "get", "set", "add", "also", "please",
    "when", "where", "how", "what", "why", "which", "file", "code", "new",
})

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_OUTCOMES_FILE = os.path.join(_DATA_DIR, "outcomes.jsonl")


def extract_keywords(text: str) -> list[str]:
    """Extract tech-relevant keywords from a task description.

    Prioritises known tech terms; also includes longer project-specific words.
    Limited to 20 keywords per task to keep records compact.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []

    # Pass 1: known tech terms (higher value)
    for word in words:
        if word in _TECH_TERMS and word not in seen:
            seen.add(word)
            keywords.append(word)

    # Pass 2: longer unknown words (project-specific jargon, e.g. "PlayerController")
    for word in words:
        if len(word) >= 6 and word not in _STOPWORDS and word not in seen:
            seen.add(word)
            keywords.append(word)

    return keywords[:20]


def extract_tool_names(messages: list[dict]) -> list[str]:
    """Extract unique tool names from a MessageHistory._messages list."""
    names: set[str] = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue
            # Handle both {"name": ...} and {"function": {"name": ...}} formats
            name = tc.get("name") or (tc.get("function") or {}).get("name")
            if name:
                names.add(str(name))
    return sorted(names)


class OutcomeTracker:
    """Append-only JSONL sink for task outcomes.

    Usage (called from AgentRunner after task completion):

        tracker = OutcomeTracker()
        tracker.record(
            task="fix the animation loop",
            tools_used=["read_file", "write_file"],
            files_modified=[{"relative": "Assets/Player.cs"}],
            tokens=4200,
            iterations=7,
            success=True,
            session_id="20260301_...",
            project_name="unity",
            skill_names=["unity-support"],
        )
    """

    def __init__(self, data_dir: str | None = None):
        base = data_dir or _DATA_DIR
        os.makedirs(base, exist_ok=True)
        self._path = os.path.join(base, "outcomes.jsonl")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        task: str,
        tools_used: list[str],
        files_modified: list[dict],
        tokens: int,
        iterations: int,
        success: bool,
        session_id: str = "",
        project_name: str = "",
        skill_names: list[str] | None = None,
    ) -> None:
        """Append one outcome record."""
        try:
            file_exts = list({
                os.path.splitext(f.get("relative", ""))[1].lower()
                for f in files_modified
                if f.get("relative") and os.path.splitext(f["relative"])[1]
            })

            entry = {
                "ts": time.time(),
                "task": task[:300],
                "keywords": extract_keywords(task),
                "tools_used": tools_used,
                "file_extensions": file_exts[:10],
                "tokens": tokens,
                "iterations": iterations,
                "success": success,
                "session_id": session_id,
                "project_name": project_name,
                "skill_names": skill_names or [],
            }
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.warning("OutcomeTracker.record failed: %s", e)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self, limit: int = 2000) -> list[dict]:
        """Return the most recent *limit* outcome records (oldest first)."""
        if not os.path.isfile(self._path):
            return []
        records: list[dict] = []
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError as e:
            logger.warning("OutcomeTracker.load failed: %s", e)
        return records

    def count(self) -> int:
        """Count total recorded outcomes (fast line-count)."""
        if not os.path.isfile(self._path):
            return 0
        try:
            with open(self._path, "rb") as fh:
                return sum(1 for _ in fh)
        except OSError:
            return 0
