"""Task decomposer: breaks complex tasks into sub-tasks using an LLM call.

Usage:
    decomposer = TaskDecomposer(provider)
    sub_tasks = decomposer.decompose("Implement a full inventory system", project_path)
    # Returns: [SubTask(title="...", description="...", role="coder", priority=10), ...]
"""

import json
import logging
from dataclasses import dataclass, field

from orchestrator.providers.base import LLMProvider

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """\
You are a task decomposition engine for an autonomous AI coding agent.

Given a complex task, break it into smaller, ordered sub-tasks that can be executed sequentially by specialized agents.

Available roles:
- **coder**: Full read/write access. Implements features, fixes bugs, creates files.
- **reviewer**: Read-only access. Reviews code, finds issues, suggests improvements. Produces a report.
- **tester**: Can write test files only. Generates tests appropriate for the project's language and framework.

Rules:
- Each sub-task must be self-contained and independently executable.
- Order sub-tasks by dependency (prerequisite tasks first).
- Assign the most appropriate role to each sub-task.
- Keep sub-tasks focused: one responsibility per sub-task.
- Total sub-tasks should be 2-6 (not too granular, not too broad).
- For simple tasks, return just 1 sub-task with role "coder".

Respond with ONLY a JSON array of objects, no other text:
[
  {
    "title": "Short descriptive title",
    "description": "Detailed instructions for the agent",
    "role": "coder|reviewer|tester",
    "priority": 10
  }
]

Priority: higher = more important. Use 10 for normal, 20 for critical, 5 for follow-up.
"""


@dataclass
class SubTask:
    """A decomposed sub-task."""
    title: str
    description: str
    role: str = "coder"
    priority: int = 10
    depends_on: list[int] = field(default_factory=list)


class TaskDecomposer:
    """Uses an LLM to decompose complex tasks into sub-tasks."""

    VALID_ROLES = {"coder", "reviewer", "tester"}

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def decompose(self, task: str, context: str = "") -> list[SubTask]:
        """Decompose a task into sub-tasks.

        Args:
            task: The complex task description.
            context: Optional project context (file list, conventions, etc.).

        Returns:
            List of SubTask objects, ordered by execution sequence.
        """
        messages = [
            {"role": "system", "content": DECOMPOSE_PROMPT},
        ]

        user_msg = f"Task to decompose:\n{task}"
        if context:
            user_msg += f"\n\nProject context:\n{context}"
        messages.append({"role": "user", "content": user_msg})

        try:
            response = self.provider.chat_completion(
                messages=messages, temperature=0, max_tokens=2048,
            )
        except Exception as e:
            logger.error("Decomposition LLM call failed: %s", e)
            # Fallback: return single task with coder role
            return [SubTask(title=task[:80], description=task, role="coder")]

        return self._parse_response(response.content or "", task)

    def _parse_response(self, content: str, original_task: str) -> list[SubTask]:
        """Parse the LLM's JSON response into SubTask objects."""
        # Try to extract JSON from response
        content = content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            items = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse decomposition response, using original task")
            return [SubTask(title=original_task[:80], description=original_task, role="coder")]

        if not isinstance(items, list) or len(items) == 0:
            return [SubTask(title=original_task[:80], description=original_task, role="coder")]

        sub_tasks = []
        for item in items:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "coder")
            if role not in self.VALID_ROLES:
                role = "coder"

            sub_tasks.append(SubTask(
                title=item.get("title", "Untitled")[:120],
                description=item.get("description", item.get("title", "")),
                role=role,
                priority=item.get("priority", 10),
            ))

        return sub_tasks if sub_tasks else [
            SubTask(title=original_task[:80], description=original_task, role="coder")
        ]
