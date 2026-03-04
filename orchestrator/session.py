"""Session persistence: save/load conversation state to disk."""

import json
import os
import logging
import re
import secrets
from datetime import datetime

logger = logging.getLogger(__name__)

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "sessions")


class SessionManager:
    """
    Persists conversation sessions to JSON files on disk.

    Each session contains:
    - messages: full conversation history
    - metadata: project, task, timestamps, budget state
    - files_modified: list of modified files for rollback
    """

    _VALID_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(self, sessions_dir: str | None = None):
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        os.makedirs(self.sessions_dir, exist_ok=True)

    @classmethod
    def _validate_id(cls, session_id: str) -> str:
        """Validate session_id to prevent path traversal."""
        if not session_id or not cls._VALID_ID.match(session_id):
            raise ValueError(f"Invalid session_id: {session_id!r}")
        return session_id

    def save(
        self,
        session_id: str,
        messages: list[dict],
        project_path: str,
        task: str,
        budget_state: dict,
        files_modified: list[dict],
        name: str = "",
    ):
        """Save a session to disk."""
        self._validate_id(session_id)
        session = {
            "id": session_id,
            "name": name or task[:50],
            "project": project_path,
            "task": task,
            "created": datetime.now().isoformat(),
            "budget": budget_state,
            "files_modified": files_modified,
            "messages": messages,
        }

        path = os.path.join(self.sessions_dir, f"{session_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info("Session saved: %s", path)

    def load(self, session_id: str) -> dict | None:
        """Load a session from disk."""
        self._validate_id(session_id)
        path = os.path.join(self.sessions_dir, f"{session_id}.json")
        if not os.path.isfile(path):
            return None

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_sessions(self, project_path: str | None = None) -> list[dict]:
        """
        List all saved sessions, optionally filtered by project.

        Returns list of session summaries (without full messages).
        """
        sessions = []

        for filename in sorted(os.listdir(self.sessions_dir), reverse=True):
            if not filename.endswith(".json"):
                continue

            path = os.path.join(self.sessions_dir, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if project_path and data.get("project") != project_path:
                    continue

                sessions.append({
                    "id": data["id"],
                    "name": data.get("name", data.get("task", "")[:50]),
                    "project": data.get("project", ""),
                    "task": data.get("task", "")[:100],
                    "created": data.get("created", ""),
                    "message_count": len(data.get("messages", [])),
                    "files_modified": len(data.get("files_modified", [])),
                    "budget": data.get("budget", {}),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file."""
        self._validate_id(session_id)
        path = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    def rename(self, session_id: str, new_name: str) -> bool:
        """Rename a session."""
        self._validate_id(session_id)
        path = os.path.join(self.sessions_dir, f"{session_id}.json")
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["name"] = new_name.strip()[:100]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True

    def generate_id(self) -> str:
        """Generate a unique session ID."""
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
