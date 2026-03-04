"""Unified async agent loop. Single canonical implementation used by both CLI and web."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from orchestrator.config import AgentConfig
from orchestrator.budget import BudgetTracker
from orchestrator.memory import MemoryManager
from orchestrator.message_history import MessageHistory
from orchestrator.resilience import ResilientProvider
from orchestrator.tool_dispatcher import ToolDispatcher
from orchestrator.session import SessionManager
from orchestrator.providers.base import LLMProvider
from orchestrator import events as evt
from orchestrator.exceptions import ContextOverflowError
from tools.registry import ToolRegistry
from sandbox.path_validator import PathValidator
from sandbox.backup_manager import BackupManager
from skills.manager import SkillManager
from orchestrator.context_store import ContextStore

logger = logging.getLogger(__name__)

# Type alias for event callback
EventCallback = Callable[[evt.AgentEvent], Awaitable[None]]


@dataclass
class AgentResult:
    """Result of an agent run."""
    success: bool
    response: str | None = None
    error: str | None = None
    iterations: int = 0
    tokens: int = 0
    session_id: str | None = None
    files_modified: list[dict] = field(default_factory=list)


class AgentRunner:
    """
    Unified async agent loop.

    Key invariants:
    - temperature=0, seed=42 for determinism
    - stream=False (required for reliable tool calling)
    - Max iterations and token budget enforced
    - Every tool call goes through sandbox validation
    - Config-driven validation before write_file (when enabled)
    - Loop detection with escalating redirections
    - Session save on completion and budget exhaustion
    """

    # Base role-specific tool restrictions (framework tools added dynamically)
    ROLE_TOOLS = {
        "coder": None,  # None = all tools available
        "reviewer": ["think", "read_file", "list_files", "search_in_files", "memory"],
        "tester": ["think", "read_file", "list_files", "search_in_files", "write_file", "memory"],
    }

    def __init__(
        self,
        config: AgentConfig,
        provider: LLMProvider,
        project_path: str,
        session_mgr: SessionManager | None = None,
        role: str | None = None,
        task_queue=None,
        scheduler=None,
        skill_manager: SkillManager | None = None,
        context_store: ContextStore | None = None,
    ):
        self.config = config
        # Wrap provider with resilience (retry + circuit breaker)
        if isinstance(provider, ResilientProvider):
            self.provider = provider
        else:
            self.provider = ResilientProvider(provider)
        self.project_path = project_path
        self.session_mgr = session_mgr or SessionManager()
        self.memory = MemoryManager()
        self.role = role  # None = default (coder), or "coder"/"reviewer"/"tester"
        self.skill_manager = skill_manager or SkillManager.empty()
        self.context_store = context_store

        self._llm_profile = self._resolve_llm_profile()
        logger.info("LLM profile: %s", self._llm_profile)

        self.tools = ToolRegistry()
        self.tools.register_all_defaults(enabled_tools=config.enabled_tools)
        self._setup_delegate_tool(task_queue)
        self._setup_schedules_tool(scheduler)
        self._setup_context_tool()
        self.skill_manager.register_tools(self.tools, role=self.role)

        # Compact profile: keep only core tools
        if self._llm_profile == "compact":
            core = {"think", "read_file", "write_file", "list_files", "search_in_files"}
            for name in list(self.tools.names):
                if name not in core:
                    self.tools.unregister(name)
        self.sandbox = PathValidator(
            allowed_prefix=config.allowed_path_prefix.strip("/").strip("\\"),
            blocked_prefixes=[p.strip("/").strip("\\") for p in config.blocked_prefixes],
            write_blocked_prefixes=[p.strip("/").strip("\\") for p in config.write_blocked_prefixes],
        )
        self.backup = BackupManager(
            os.path.join(os.path.dirname(__file__), "..", config.backup_dir)
        )
        self.history = MessageHistory(
            max_tokens=config.max_context_tokens,
            read_only_threshold=15 if self._llm_profile == "compact" else 8,
        )
        self.budget = BudgetTracker(
            max_iterations=config.max_iterations,
            max_total_tokens=config.max_total_tokens,
            max_context_tokens=config.max_context_tokens,
        )
        self.dispatcher = ToolDispatcher(self.tools, self.sandbox, self.backup)

        self._budget_warned = False
        self._loop_warnings = 0
        self._write_mode = False
        self._checkpoint_interval = 5  # Save checkpoint every N iterations

    def _resolve_llm_profile(self) -> str:
        """Resolve the effective LLM profile (auto/compact/default)."""
        profile = self.config.llm_profile
        if profile == "auto":
            return "compact" if self.config.max_context_tokens <= 8192 else "default"
        return profile

    def _setup_delegate_tool(self, task_queue):
        """Register the delegate tool and wire its queue reference."""
        from tools.delegate_tool import DelegateTool
        delegate = DelegateTool()
        delegate._queue = task_queue
        self.tools.register(delegate)

    def _setup_schedules_tool(self, scheduler):
        """Wire scheduler reference into manage_schedules tool if registered."""
        if scheduler is None:
            return
        tool = self.tools.get("manage_schedules")
        if tool:
            tool._scheduler = scheduler

    def _setup_context_tool(self):
        """Wire context_store reference into manage_context tool if registered."""
        if self.context_store is None:
            return
        tool = self.tools.get("manage_context")
        if tool:
            tool._context_store = self.context_store

    async def run(
        self,
        task: str,
        on_event: EventCallback | None = None,
        resume_session_id: str | None = None,
    ) -> AgentResult:
        """Execute a task against a project, emitting events via callback."""
        session_id = self.session_mgr.generate_id()
        self._session_name = task[:50]

        async def emit(event: evt.AgentEvent):
            if on_event:
                await on_event(event)

        # Build system prompt (with contextual skill injections)
        system_prompt = self._build_system_prompt_for_task(task)
        self.history.set_system(system_prompt)

        # Resume from previous session if requested
        if resume_session_id:
            prev = self.session_mgr.load(resume_session_id)
            if prev and prev.get("messages"):
                self._session_name = prev.get("name", task[:50])
                for msg in prev["messages"]:
                    if msg.get("role") == "system":
                        continue
                    self.history._messages.append(msg)
                self.history.add_user(f"[Continuing from previous session]\n{task}")
                await emit(evt.info(
                    f"Resumed from session {resume_session_id} ({len(prev['messages'])} messages)"
                ))
            else:
                self.history.add_user(task)
        else:
            self.history.add_user(task)

        await emit(evt.agent_start(
            task=task,
            project=self.project_path,
            session_id=session_id,
            max_iterations=self.config.max_iterations,
            provider=self.provider.provider_name,
            model=self.provider.model_name,
        ))

        # ---- Main agent loop ----
        while not self.budget.exhausted:
            self.budget.tick()

            await emit(evt.iteration(
                current=self.budget.iteration,
                max_iter=self.budget.max_iterations,
                tokens=self.budget.total_tokens,
                max_tokens=self.budget.max_total_tokens,
            ))

            # Budget warning at 80%
            if self.budget.warning_zone and not self._budget_warned:
                self._budget_warned = True
                self.history.add_user(
                    f"BUDGET WARNING: {self.budget.iteration}/{self.budget.max_iterations} iterations, "
                    f"{self.budget.total_tokens}/{self.budget.max_total_tokens} tokens used. "
                    "You MUST finish NOW. Call think() to summarize what you've done, "
                    "then respond with a final text message (no tool call)."
                )
                await emit(evt.warning("Budget warning: wrapping up"))

            # Select tool schemas based on mode and role
            if self._loop_warnings >= 3:
                active_schemas = []
            elif self._write_mode:
                active_schemas = self.tools.schemas_only(self.tools.get_write_mode_tools())
            else:
                role_tools = self.ROLE_TOOLS.get(self.role)
                if role_tools is not None:
                    # Dynamically add registered framework tools to role lists
                    expanded = list(role_tools)
                    for extra in ["validate_csharp", "unity_logs", "manage_schedules"]:
                        if extra in self.tools.names and extra not in expanded:
                            expanded.append(extra)
                    active_schemas = self.tools.schemas_only(expanded)
                else:
                    active_schemas = self.tools.schemas

            # Call LLM (blocking call wrapped in thread)
            try:
                response = await asyncio.to_thread(
                    self.provider.chat_completion,
                    messages=self.history.messages,
                    tools=active_schemas or None,
                    temperature=self.config.temperature,
                    seed=self.config.seed,
                    max_tokens=self.config.max_tokens,
                )
            except ContextOverflowError as e:
                logger.error("Context overflow: %s", e)
                await emit(evt.error(
                    f"System prompt too large for model context window "
                    f"({self.config.max_context_tokens} tokens). "
                    "Increase context length in LLM settings or reduce user context/skills."
                ))
                return AgentResult(
                    success=False,
                    error=str(e),
                    iterations=self.budget.iteration,
                    tokens=self.budget.total_tokens,
                    session_id=session_id,
                    files_modified=self.backup.modified_files,
                )
            except Exception as e:
                logger.error("LLM error: %s", e)
                await emit(evt.error(f"LLM error: {e}"))
                return AgentResult(
                    success=False,
                    error=str(e),
                    iterations=self.budget.iteration,
                    tokens=self.budget.total_tokens,
                    session_id=session_id,
                    files_modified=self.backup.modified_files,
                )

            # Track token usage
            self.budget.add_usage(
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            )

            # No tool calls = agent might be done
            if not response.tool_calls:
                content = response.content or ""
                self.history.add_assistant(content)

                # Detect false completion
                if self._is_false_completion(content):
                    logger.warning("False completion detected, pushing agent to act")
                    self.history.add_user(
                        "You just described what you plan to do but did NOT actually do it. "
                        "STOP talking. Use your tools NOW to implement the changes. "
                        "Call think() then the appropriate tool."
                    )
                    await emit(evt.warning("False completion detected — pushing agent to act"))
                    continue

                # Agent is done
                await emit(evt.agent_response(content))

                self._save_session(session_id, task)
                self._log_memory(task, content)
                self._record_outcome(task, session_id, success=True)

                result = AgentResult(
                    success=True,
                    response=content,
                    iterations=self.budget.iteration,
                    tokens=self.budget.total_tokens,
                    session_id=session_id,
                    files_modified=self.backup.modified_files,
                )
                await emit(evt.agent_done(
                    success=True,
                    session_id=session_id,
                    iterations=self.budget.iteration,
                    tokens=self.budget.total_tokens,
                    files_modified=[f["relative"] for f in self.backup.modified_files],
                ))
                return result

            # Process tool call
            self.history.add_assistant_tool_call(response.content, response.tool_calls)
            tool_call = response.tool_calls[0]

            tool_name = tool_call["name"]
            tool_args_raw = tool_call["arguments"]

            # Parse arguments for UI display
            try:
                tool_args_parsed = json.loads(tool_args_raw)
            except (json.JSONDecodeError, TypeError):
                tool_args_parsed = {"_raw": str(tool_args_raw)[:200]}

            await emit(evt.tool_call(tool_name, tool_args_parsed))

            # Execute tool (blocking, run in thread)
            result_str = await asyncio.to_thread(
                self.dispatcher.dispatch, tool_call, self.project_path
            )

            # Parse result for UI display
            try:
                result_json = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                result_json = {"raw": str(result_str)[:500]}

            self.history.add_tool_result(tool_call["id"], result_str)
            await emit(evt.tool_result(tool_name, result_json))

            # Loop detection with escalating redirections
            loop_type = self.history.detect_loop()
            if loop_type:
                self._loop_warnings += 1
                # read_only_spinning / duplicate_reads → skip straight to write mode
                if loop_type in ("read_only_spinning", "duplicate_reads") and self._loop_warnings < 2:
                    self._loop_warnings = 2
                logger.warning("Loop detected (%s), warning #%d", loop_type, self._loop_warnings)

                if self._loop_warnings >= 3:
                    self.history.add_user(
                        "CRITICAL: You have been looping for too long. "
                        "All tools have been REMOVED. "
                        "Respond NOW with a text summary of what you accomplished."
                    )
                    await emit(evt.warning("Force finish — all tools removed"))
                elif self._loop_warnings >= 2:
                    self._write_mode = True
                    write_tools = ", ".join(self.tools.get_write_mode_tools())
                    if self._llm_profile == "compact":
                        self.history.add_user(
                            "WRITE MODE. You can ONLY use: think and write_file. "
                            "Example: write_file(path='file.txt', content='your content here'). "
                            "Do it NOW or respond with a summary to finish."
                        )
                    else:
                        self.history.add_user(
                            "WRITE MODE ACTIVATED. read_file, list_files, and search_in_files "
                            f"have been REMOVED. You can ONLY use: {write_tools}. "
                            "You have already read all the files you need. "
                            "Use write_file NOW to implement your changes, or respond with a summary to finish."
                        )
                    await emit(evt.warning("WRITE MODE — read tools removed"))
                else:
                    self.history.add_user(
                        f"Loop detected ({loop_type}). You are repeating actions. "
                        "Call think() to reassess. What have you already done? "
                        "What concrete action can you take that is DIFFERENT from what you just did?"
                    )
                    await emit(evt.warning(f"Loop detected ({loop_type}), warning #{self._loop_warnings}"))

            # Checkpoint every N iterations (for crash recovery)
            if (self.budget.iteration % self._checkpoint_interval == 0
                    and self.budget.iteration > 0):
                self._save_session(session_id, task)

            # Progress injection every 10 iterations
            if self.budget.iteration % 10 == 0 and self.budget.iteration > 0:
                files_modified = [f["relative"] for f in self.backup.modified_files]
                self.history.add_user(
                    f"PROGRESS CHECK (iteration {self.budget.iteration}/{self.budget.max_iterations}): "
                    f"Files modified so far: {files_modified or 'none'}. "
                    "Are you making progress? If not, call think() to reassess or finish."
                )

        # Budget exhausted — save session for future resume
        self._save_session(session_id, task)
        self._log_memory(task, "Budget exhausted")
        self._record_outcome(task, session_id, success=False)

        result = AgentResult(
            success=False,
            error="Budget exhausted",
            iterations=self.budget.iteration,
            tokens=self.budget.total_tokens,
            session_id=session_id,
            files_modified=self.backup.modified_files,
        )
        await emit(evt.agent_done(
            success=False,
            error="Budget exhausted",
            session_id=session_id,
            iterations=self.budget.iteration,
            tokens=self.budget.total_tokens,
            files_modified=[f["relative"] for f in self.backup.modified_files],
        ))
        return result

    def _save_session(self, session_id: str, task: str):
        """Persist session to disk."""
        self.session_mgr.save(
            session_id=session_id,
            messages=self.history._messages,
            project_path=self.project_path,
            task=task,
            budget_state=self.budget.status(),
            files_modified=self.backup.modified_files,
            name=self._session_name,
        )

    def _record_outcome(self, task: str, session_id: str, success: bool) -> None:
        """Record task outcome to outcomes.jsonl for pattern analysis."""
        try:
            from orchestrator.outcome_tracker import OutcomeTracker, extract_tool_names
            tools_used = extract_tool_names(self.history._messages)
            OutcomeTracker().record(
                task=task,
                tools_used=tools_used,
                files_modified=self.backup.modified_files,
                tokens=self.budget.total_tokens,
                iterations=self.budget.iteration,
                success=success,
                session_id=session_id,
                project_name=self.config.project_name,
                skill_names=[s.name for s in self.skill_manager.skills],
            )
        except Exception as e:
            logger.warning("Failed to record outcome: %s", e)

    def _log_memory(self, task: str, result_summary: str):
        """Log activity to persistent memory."""
        try:
            self.memory.log_activity(
                task=task,
                result_summary=result_summary,
                files_modified=[f["relative"] for f in self.backup.modified_files],
            )
        except Exception as e:
            logger.warning("Failed to log to memory: %s", e)

    def _build_system_prompt(self) -> str:
        """Load system prompt from file and inject project context."""
        prompts_base = os.path.join(os.path.dirname(__file__), "..", self.config.prompts_dir)

        # Compact profile: use compact.md, skip optional injections
        if self._llm_profile == "compact":
            compact_path = os.path.join(prompts_base, "profiles", "compact.md")
            if os.path.isfile(compact_path):
                with open(compact_path, "r", encoding="utf-8") as f:
                    base_prompt = f.read()
            else:
                base_prompt = (
                    "You are an autonomous coding agent. "
                    "Call think() before every action. Use write_file to create files. "
                    "Respond with a text summary when done."
                )
            prompt = f"{base_prompt}\n\n## Project Context\n- Project path: {self.project_path}\n"
            prompt += self._build_environment_section()
            return prompt

        # Default profile: full prompt cascade with all injections
        candidates = [
            os.path.join(prompts_base, "profiles", f"{self.config.project_name}.md"),
            os.path.join(prompts_base, "profiles", "generic.md"),
            os.path.join(prompts_base, "system_prompt.md"),
        ]

        base_prompt = None
        for path in candidates:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    base_prompt = f.read()
                break

        if base_prompt is None:
            base_prompt = (
                "You are an autonomous coding agent. "
                "Use think() before every action. Never repeat tool calls. "
                "Finish with a text summary when done."
            )
        prompt = f"{base_prompt}\n\n## Project Context\n- Project path: {self.project_path}\n"

        # Inject environment section (sandbox rules, enabled tools, config paths)
        prompt += self._build_environment_section()

        # Inject role-specific prompt
        if self.role:
            role_path = os.path.join(
                os.path.dirname(__file__), "..", self.config.prompts_dir,
                "roles", f"{self.role}.md"
            )
            if os.path.isfile(role_path):
                with open(role_path, "r", encoding="utf-8") as f:
                    prompt += f"\n{f.read()}\n"

        # Inject memory context
        memory_ctx = self.memory.get_context_for_task("")
        if memory_ctx:
            prompt += f"\n{memory_ctx}"

        # Inject user context items (filtered by role scope)
        if self.context_store:
            user_ctx = self.context_store.get_active_text(role=self.role)
            if user_ctx:
                prompt += f"\n{user_ctx}"

        return prompt

    def _build_environment_section(self) -> str:
        """Build the ## Environment section injected into the system prompt."""
        cfg = self.config
        tools_list = ", ".join(sorted(self.tools.names))
        allowed = cfg.allowed_path_prefix or "all (project root)"
        blocked = ", ".join(cfg.blocked_prefixes) if cfg.blocked_prefixes else "none"
        write_blocked = ", ".join(cfg.write_blocked_prefixes) if cfg.write_blocked_prefixes else "none"
        lines = [
            "\n## Environment",
            f"- Profile: {self._llm_profile}",
            f"- Enabled tools: {tools_list}",
            f"- Sandbox: read-allowed={allowed}, read-blocked=[{blocked}], write-blocked=[{write_blocked}]",
            f"- Config: config/default.yaml (main), config/schedules.yaml (cron schedules)",
            f"- Schedules: config/schedules.yaml — templates in prompts/task_templates/automation/",
            f"- Memory: .clu/memory/ — Context rules: .clu/user-context.json",
            "- Limits: read_file max 100KB, write_file max 50KB, list_files max 200 results, search max 50 results",
        ]
        return "\n".join(lines) + "\n"

    # System prompt should use at most 50% of context window
    # (leaving room for tool schemas, conversation history, and response)
    PROMPT_BUDGET_RATIO = 0.5

    def _build_system_prompt_for_task(self, task: str) -> str:
        """Build system prompt with contextual skill injections for a specific task."""
        base = self._build_system_prompt()
        # Compact profile: skip skill injections entirely
        if self._llm_profile == "compact":
            return self._enforce_prompt_budget(base)
        skill_ctx = self.skill_manager.get_prompt_injections(task)
        if skill_ctx:
            base = f"{base}\n\n{skill_ctx}"
        return self._enforce_prompt_budget(base)

    def _enforce_prompt_budget(self, prompt: str) -> str:
        """Trim optional sections if the system prompt exceeds the context budget.

        Uses conservative token estimation (3 chars ≈ 1 token) and strips
        sections in order of decreasing expendability:
        skills → memory → user context.
        """
        budget = int(self.config.max_context_tokens * self.PROMPT_BUDGET_RATIO)
        if budget <= 0 or len(prompt) // 3 <= budget:
            return prompt

        logger.warning(
            "System prompt too large (~%d tokens, budget %d). Trimming optional sections.",
            len(prompt) // 3, budget,
        )

        # Strip in priority order (least important first)
        strip_markers = [
            "\n\n## Skill Context",
            "\n## Agent Memory",
            "\n## User Context",
        ]
        for marker in strip_markers:
            idx = prompt.find(marker)
            if idx >= 0:
                prompt = prompt[:idx]
                logger.info("Stripped '%s' section from system prompt", marker.strip())
                if len(prompt) // 3 <= budget:
                    break

        return prompt

    def _is_false_completion(self, content: str) -> bool:
        """Detect when the LLM responds with intent text instead of using tools."""
        if not content or len(content) < 20:
            return False
        if self.backup.modified_files:
            return False
        if self._loop_warnings >= 3:
            return False

        intent_phrases = [
            "i'll ", "i will ", "let me ", "i need to ", "i should ",
            "i'm going to ", "let's ", "i can ", "i plan to ",
            "here's my plan", "here is my plan",
            "i'll now ", "now i'll ", "next, i'll ",
            "implement this", "implement the",
        ]
        content_lower = content.lower()
        return any(phrase in content_lower for phrase in intent_phrases)
