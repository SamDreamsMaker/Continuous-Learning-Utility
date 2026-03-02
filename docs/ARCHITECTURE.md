# CLU — Architecture & Internal Reference

> Exhaustive technical documentation for contributors and developers.
> Updated: 2026-03-03

## 1. Overview

CLU (Continuous Learning Utility) is an autonomous 24/7 AI coding agent. It supports local LLMs
(LM Studio, Ollama, vLLM) and cloud providers (Anthropic Claude, Google Gemini, OpenAI).
It follows a THINK → ACT → OBSERVE loop with a persistent daemon, task queue, heartbeat monitoring,
scheduled tasks, multi-agent roles, and external integrations.

- **Language**: Python 3.13+
- **LLM**: Any OpenAI-compatible, Anthropic, or Google provider
- **Interface**: Web dashboard (FastAPI + WebSocket + vanilla JS)
- **Validation**: Optional per-language validators (C# via dotnet build included)
- **Daemon**: Separate process polling a SQLite task queue 24/7

CLU is **language-agnostic** — configure `project.language`, `project.source_dir`, and
`project.file_extensions` in YAML to target any codebase. The default config is generic
(any language). Unity/C# and Python profiles are included as examples.

## 2. Project Tree

```
CLU/
├── main.py                          # CLI entry point (web, task, interactive, rollback, daemon)
├── setup.bat                        # Auto-setup: Python + venv + deps (Windows)
├── run.bat                          # Launcher with auto-setup (Windows)
├── run_daemon.bat                   # Daemon launcher with auto-restart (Windows)
├── run_daemon.sh                    # Daemon launcher (Linux/macOS)
├── requirements.txt                 # Python dependencies
├── LICENSE                          # MIT License
├── README.md                        # Project overview and quick start
│
├── config/
│   ├── default.yaml                 # Main config (API, LLM, budget, security, validation, tools)
│   ├── schedules.yaml               # Cron schedule definitions
│   └── profiles/                    # Language/framework profiles
│       ├── unity.yaml               # Unity/C# profile (optional)
│       └── python.yaml              # Python project example
│
├── daemon/                          # 24/7 daemon subsystem
│   ├── daemon.py                    # AgentDaemon main loop (queue → execute → heartbeat → schedule)
│   ├── service.py                   # Start/stop/status via PID file + subprocess
│   ├── task_queue.py                # SQLite task queue (ACID, WAL, priority, retry, dead letter)
│   ├── heartbeat.py                 # HeartbeatManager (free checks when queue is empty)
│   ├── scheduler.py                 # TaskScheduler (cron-like, YAML config, template resolution)
│   ├── cron_parser.py               # Custom 5-field cron parser (no external deps)
│   ├── webhooks.py                  # WebhookHandler (GitHub issues/push + generic webhooks)
│   ├── notifiers.py                 # NotificationManager (Desktop/Discord/Slack)
│   ├── alerts.py                    # AlertManager (JSON file persistence, read/unread tracking)
│   └── checks/                      # Heartbeat check plugins
│       ├── base.py                  # BaseCheck abstract class
│       ├── unity_compile.py         # Unity Editor.log compile error detection (optional)
│       ├── new_files.py             # Detects source files modified since last check
│       ├── todo_markers.py          # Scans TODO/FIXME/HACK markers (// and # comments)
│       └── large_files.py           # Source files exceeding configurable line threshold
│
├── orchestrator/                    # Core agent engine
│   ├── runner.py                    # AgentRunner — unified async loop with event callbacks
│   ├── events.py                    # AgentEvent hierarchy (dataclasses)
│   ├── agent.py                     # Sync CLI wrapper around AgentRunner
│   ├── budget.py                    # BudgetTracker (iterations + completion tokens)
│   ├── client.py                    # LMStudioClient (legacy, used by agent.py)
│   ├── config.py                    # AgentConfig dataclass + YAML loading
│   ├── exceptions.py                # Custom exception hierarchy
│   ├── message_history.py           # Message history + trimming + loop detection
│   ├── session.py                   # SessionManager (JSON persistence on disk)
│   ├── tool_dispatcher.py           # Tool call dispatch from LLM → handlers
│   ├── memory.py                    # MemoryManager (daily logs, knowledge categories, context injection)
│   ├── resilience.py                # ResilientProvider (retry + circuit breaker + failover)
│   ├── decomposer.py               # TaskDecomposer (LLM-based task splitting into sub-tasks)
│   ├── context_store.py             # ContextStore: user context items with role scopes (always/coder/reviewer/tester)
│   ├── outcome_tracker.py           # OutcomeTracker: appends task outcomes to data/outcomes.jsonl
│   └── providers/                   # Multi-LLM provider abstraction
│       ├── base.py                  # LLMProvider ABC + LLMResponse dataclass
│       ├── factory.py               # create_provider(type, url, key, model)
│       ├── openai_compat.py         # LM Studio, OpenAI, Ollama, vLLM (via openai SDK)
│       ├── anthropic_provider.py    # Claude models (via anthropic SDK)
│       └── google_provider.py       # Gemini models (via google-genai SDK)
│
├── skills/                          # Extensible skills system
│   ├── __init__.py
│   ├── exceptions.py                # SkillLoadError, SkillIntegrityError, SkillRequirementError
│   ├── manifest.py                  # SkillManifest dataclass + SHA-256 integrity + keyword matching
│   ├── loader.py                    # SkillLoader: 4-tier discovery, secret scan, injection detect, topo sort
│   ├── manager.py                   # SkillManager: tool registration, prompt injection, summary, state_store
│   ├── test_runner.py               # SkillTestRunner: declarative test execution
│   ├── state.py                     # SkillStateStore: persist enable/disable + auto_generate (~/.clu/skills-state.json)
│   ├── registry.py                  # SkillRegistry: sync/publish/list/install from community GitHub registry
│   ├── pattern_analyzer.py          # PatternAnalyzer: Jaccard clustering of outcomes.jsonl → SkillCandidate list
│   ├── generator.py                 # SkillGenerator: LLM-powered skill generation + full security pipeline
│   └── bundled/                     # Skills shipped with CLU
│       ├── unity-support/           # Unity/C# coding guidelines (win32 only, requires Assets/)
│       ├── todo-tracker/            # TODO/FIXME/HACK scanner across all source languages
│       └── code-conventions/        # Generic code quality guidelines (prompt injection)
│
├── tools/                           # 13 LLM tools
│   ├── base.py                      # BaseTool abstract class (to_openai_schema)
│   ├── registry.py                  # ToolRegistry + lazy import via TOOL_MAP
│   ├── think.py                     # ThinkTool — forces LLM to plan (no-op)
│   ├── read_file.py                 # ReadFileTool — reads files with line numbers
│   ├── write_file.py                # WriteFileTool — full write or incremental patches
│   ├── list_files.py                # ListFilesTool — directory listing with glob
│   ├── search_in_files.py           # SearchInFilesTool — regex search across files
│   ├── validate_csharp.py           # ValidateCSharpTool — C# validation (optional)
│   ├── unity_logs.py                # UnityLogsTool — Unity Editor logs (optional)
│   ├── memory_tool.py               # MemoryTool — read/write/append/log knowledge
│   ├── delegate_tool.py             # DelegateTool — enqueue sub-tasks for other roles
│   ├── manage_schedules.py          # ManageSchedulesTool — CRUD on cron schedules
│   └── manage_context.py            # ManageContextTool — list/add/disable/delete user context items
│
├── prompts/
│   ├── system_prompt.md             # Default system prompt (THINK → ACT → OBSERVE protocol)
│   ├── profiles/                    # Language-specific + LLM-adapted system prompts
│   │   ├── unity.md                 # Unity/C# specialized prompt
│   │   ├── generic.md              # Language-agnostic prompt (default profile)
│   │   └── compact.md              # Short directive prompt for small local models (compact profile)
│   ├── roles/                       # Specialized agent role prompts
│   │   ├── coder.md                 # Full read/write access
│   │   ├── reviewer.md              # Read-only, structured reports
│   │   └── tester.md                # Read + write tests only
│   └── task_templates/
│       ├── add_feature.md
│       ├── create_script.md
│       ├── fix_bug.md
│       ├── refactor_srp.md
│       └── automation/              # Scheduled task templates
│           ├── auto_fix_compile.md
│           ├── code_review.md
│           ├── generate_docs.md
│           └── test_generation.md
│
├── validation/                      # Language-specific validation (optional)
│   ├── csharp_validator.py          # CSharpValidator (dotnet build + parse errors)
│   └── project_generator.py         # Generates minimal .csproj with Unity DLL refs
│
├── sandbox/                         # File security
│   ├── path_validator.py            # PathValidator (configurable prefix + blocklist)
│   └── backup_manager.py            # BackupManager (timestamped backup + rollback)
│
├── web/                             # Web dashboard
│   ├── server.py                    # FastAPI + WebSocket (40+ REST endpoints incl. /api/skills/*, /api/context/*)
│   ├── index.html                   # Main HTML (9-tab panel layout + Context nav tab)
│   ├── css/styles.css               # Dark theme, responsive, tabs, components
│   └── js/                          # 17 frontend modules
│       ├── utils.js                 # Globals, escHtml, formatMarkdown, copyText
│       ├── store.js                 # ProviderConfigStore + connectionState reactive singleton
│       ├── ui.js                    # Panel toggles, setRunning, addMsg, setBadge
│       ├── logs.js                  # log(), setLogFilter()
│       ├── provider.js              # Provider config, test, apply
│       ├── agent.js                 # sendTask, stopAgent, rollback
│       ├── sessions.js              # Session strip (load, resume, rename, delete, feature toggles)
│       ├── websocket.js             # WebSocket connection + message handling
│       ├── main.js                  # Status check, project setup, init
│       ├── tasks.js                 # Task queue UI (status badges, retry/cancel)
│       ├── heartbeat.js             # Heartbeat pulse indicator, manual trigger
│       ├── memory.js                # Memory browser with inline editing
│       ├── schedules.js             # Schedule CRUD with cron preview
│       ├── alerts.js                # Notification center (read/unread, badges)
│       ├── costs.js                 # Token consumption tracking
│       ├── skills.js                # Skills list, reload, per-skill test runner
│       └── context.js               # Context items CRUD (scope badges, add form with scope dropdown)
│
├── unity_plugin/                    # Unity Editor integration (optional)
│   ├── AgentBridge.cs               # EditorWindow (HTTP communication with agent)
│   └── README.md                    # Installation instructions
│
├── docs/                            # Documentation
│   └── ARCHITECTURE.md              # This file
│
├── tests/                           # 450 unit tests (pytest)
│   ├── test_agent.py                # BudgetTracker + MessageHistory + loop detection
│   ├── test_daemon.py               # TaskQueue + AgentDaemon + DaemonService
│   ├── test_heartbeat.py            # All checks + HeartbeatManager
│   ├── test_integrations.py         # Webhooks + Notifiers
│   ├── test_memory.py               # MemoryManager + MemoryTool
│   ├── test_multiagent.py           # TaskDecomposer + DelegateTool + Roles
│   ├── test_providers.py            # LLMResponse + Factory + OpenAI compat
│   ├── test_resilience.py           # Backoff + CircuitBreaker + ResilientProvider
│   ├── test_sandbox.py              # PathValidator (custom prefix, blocklist, write-blocked prefixes)
│   ├── test_scheduler.py            # CronParser + CronExpression + TaskScheduler
│   ├── test_tools.py                # All tools (read, write, list, search)
│   ├── test_manage_schedules.py     # ManageSchedulesTool CRUD operations
│   ├── test_skill_manifest.py       # SkillManifest parsing, SHA-256, requirements gating (30)
│   ├── test_skill_loader.py         # 4-tier discovery, secret scan, topo sort (26)
│   ├── test_skill_manager.py        # Tool registration, prompt injection, budget (24)
│   ├── test_skill_integrations.py   # HeartbeatManager + AgentDaemon with skills (9)
│   ├── test_skill_config.py         # AgentConfig skills fields, backward compat (15)
│   ├── test_skill_test_runner.py    # Declarative test execution, expectation engine (31)
│   ├── test_outcome_tracker.py      # OutcomeTracker append + load (21)
│   ├── test_pattern_analyzer.py     # Jaccard clustering, SkillCandidate extraction (16)
│   ├── test_skill_generator.py      # LLM-based skill generation + security pipeline (11)
│   ├── test_registry.py             # sync/publish/list/install registry operations (20)
│   └── fixtures/
│       ├── sample_valid.cs
│       └── sample_invalid.cs
│
├── scripts/
│   └── install_python.ps1           # Python auto-installer (winget + fallback)
│
├── data/                            # Runtime data (gitignored)
├── memory/                          # Persistent memory (gitignored)
├── sessions/                        # Saved sessions (gitignored)
├── backups/                         # File backups (gitignored)
└── logs/                            # Agent log files (gitignored)
```

## 3. Execution Flow

### Web Mode (primary)

```
main.py --web → FastAPI server on :8080
  → User enters a task in the chat
  → AgentRunner.run() executes the loop:

    while not budget.exhausted:
      1. Select tool schemas (normal / write-only / none) based on role
      2. Call LLM provider (stream=False for reliable tool calling)
      3. If no tool call → check false completion → finish
      4. Execute tool call via ToolDispatcher
      5. Detect loops (identical, cycle, read_only_spinning)
      6. Escalate: text warning → WRITE MODE → remove all tools
      7. Inject progress summary every 10 iterations
      8. Save session at end (success or failure)
```

### Daemon Mode (24/7)

```
main.py --daemon start → AgentDaemon main loop:

  while running:
    1. Dequeue highest-priority task from SQLite queue
    2. If task found → create AgentRunner with role → execute → complete/fail
    3. If queue empty:
       a. Run heartbeat checks (configurable: compile, new files, TODOs, large files)
       b. Auto-enqueue tasks from heartbeat findings
       c. Run scheduler tick (fire due cron jobs)
    4. Send notifications (desktop / Discord / Slack) on task events
    5. Sleep 5s → repeat
```

### LLM Protocol

```
THINK → ACT → OBSERVE → repeat → FINISH

- THINK: mandatory call to think() before each action
- ACT: one tool call per turn
- OBSERVE: receive result, feed back to LLM
- FINISH: final text response (no tool call)
```

### Multi-Agent Task Decomposition

1. User sends complex task → `POST /api/decompose-and-enqueue`
2. `TaskDecomposer` calls LLM to split into 2-6 sub-tasks with roles
3. Sub-tasks enqueued to SQLite queue with role metadata
4. Daemon processes each with role-specific tool restrictions:
   - **coder**: all tools (default)
   - **reviewer**: read-only tools (think, read_file, list_files, search_in_files, memory)
   - **tester**: read + write test files only
5. Agent can also delegate sub-tasks via `DelegateTool` during execution

## 4. Key Technical Decisions

### LLM Provider
- **`stream=False` is required** for reliable tool calling across all providers
- `temperature=0`, `seed=42` for reproducibility
- `max_tokens=4096` per completion
- Multi-provider: OpenAI-compat (local), Anthropic, Google
- Dynamic model listing from all configured providers

### Budget (completion tokens only)
- Only `completion_tokens` count toward budget (not `total_tokens`)
- Default limits: 50 iterations, 500K completion tokens, 32K context window
- `prompt_tokens` tracked for info but don't consume budget

### Context Overflow Prevention
- `ContextOverflowError`: raised by OpenAI-compat provider on 400 errors with
  `n_keep >= n_ctx` or `context_length_exceeded` — never retried
- `_enforce_prompt_budget()`: trims optional prompt sections (skills → memory → context)
  when system prompt exceeds 50% of `max_context_tokens`
- Token estimation: conservative `len(text) // 3` (no tokenizer dependency)

### LLM Profiles
- `llm.profile: "auto"` (default): selects `compact` when `max_context_tokens <= 8192`
- `compact`: short directive prompt (~300 tokens) with few-shot example, 5 core tools only
  (think, read, write, list, search), no memory/skills/context injection,
  relaxed anti-loop threshold (15 vs 8)
- `default`: full prompt, all tools, all injections

### Loop Detection (3 levels)
- `identical_calls`: 3 identical consecutive calls (same name + args)
- `cycle_N`: cyclic pattern on last 12 calls (e.g., A-B-A-B)
- `read_only_spinning`: configurable threshold (default 8, compact profile: 15)

### Anti-loop Escalation (3 warnings)
1. Text message asking the LLM to change approach
2. **WRITE MODE** — remove `read_file`, `list_files`, `search_in_files`
   (compact profile: includes concrete write_file example)
3. Remove **all tools** — force final text response

### Task Queue (SQLite)
- WAL mode for concurrent daemon/web access
- Priority-based dequeue (higher number = higher priority)
- Auto-retry with configurable `max_attempts`
- Dead letter queue for permanently failed tasks
- Task types: manual, heartbeat, scheduled, webhook

### Resilience
- `ExponentialBackoff`: delay = min(base × 2^attempt, max) + jitter
- `CircuitBreaker`: closed → open (after N failures) → half_open (test recovery)
- `ResilientProvider` wraps any LLM provider with retry + circuit breaker
- Checkpointing every N iterations for crash recovery

### Cron Scheduling
- Custom 5-field parser (minute hour dom month dow), no external deps
- Supports: `*`, `*/N`, `N-M`, `N,M,O`, range+step
- Double-fire prevention (tracks `last_run` at minute resolution)
- Templates loaded from `prompts/task_templates/automation/`

### Sandbox
- `allowed_path_prefix`: restricts CLU to a subdirectory (default: `""` = unrestricted)
- `blocked_prefixes`: paths CLU can never read or write (OS system dirs by default:
  C:/Windows, C:/Program Files, /etc, /bin, /usr, /sys, /proc, .git)
- `write_blocked_prefixes`: CLU can read but never write here (default: `.clu`)
  → prevents CLU from placing malicious Python modules in skill dirs that SkillLoader
    would execute on next startup
- `PathValidator.validate(path, root, mode="read"|"write")` — mode-aware enforcement
- Anti-traversal (`..`) and anti-symlink protection
- Max file read/write sizes enforced per config

### Persistent Memory
- Daily activity logs: `memory/daily/YYYY-MM-DD.md`
- Knowledge categories: `conventions`, `known_issues`, `project_patterns`
- Context injection: recent memory prepended to system prompt
- Auto-compaction: old logs summarized after N days

### Cross-Platform
- Windows + Linux + macOS (no OS-specific dependencies)
- Paths: `pathlib` everywhere (no hardcoded separators)
- Daemon: `subprocess.Popen` (not OS services)
- PID file + `SIGTERM` (Linux/macOS) / `taskkill` (Windows)
- Dual launcher scripts: `.bat` (Windows) + `.sh` (Linux/macOS)

## 5. LLM Tools (13 tools)

| # | Tool | Signature | Description |
|---|------|-----------|-------------|
| 1 | `think` | `(reasoning)` | No-op forcing LLM to plan. Called before each action. |
| 2 | `read_file` | `(path)` | Read file with line numbers. Max 100KB. |
| 3 | `write_file` | `(path, content?, patches?)` | Full write or incremental patches. Automatic backup. |
| 4 | `list_files` | `(path?, pattern?, recursive?)` | Directory listing. Max 200 results. |
| 5 | `search_in_files` | `(pattern, path?, file_pattern?)` | Regex search across project files. Max 50 results. |
| 6 | `validate_csharp` | `(code)` | C# validation via dotnet build. *Optional.* |
| 7 | `unity_logs` | `(mode?, source?)` | Read Unity Editor logs. *Optional.* |
| 8 | `memory` | `(action, category?, content?)` | Read/write/append persistent knowledge. |
| 9 | `delegate` | `(task, role, priority?, context?)` | Enqueue sub-task for another agent role. |
| 10 | `manage_schedules` | `(action, schedule_id?, ...)` | List/create/update/delete/toggle cron schedules. |
| 11 | `manage_context` | `(action, name?, content?, scope?)` | List/add/disable/delete user context items injected into every run. |

Tools 6-7 are framework-specific and only loaded when listed in `tools.enabled` in config.

## 6. Configuration

CLU is entirely config-driven via YAML. All values that were previously hardcoded
(source directory, file extensions, blocked paths, enabled tools, heartbeat checks)
are now configurable fields.

### Key Config Sections

```yaml
project:
  name: "generic"                # Profile name (default: generic)
  language: "any"                # Target language (empty/any = all files)
  file_extensions: []            # Source file extensions (empty = scan all)
  source_dir: ""                 # Root source directory (empty = project root)
  framework: "generic"           # Framework identifier

api:
  provider: "openai_compat"      # openai_compat | anthropic | google
  base_url: "http://localhost:1234/v1"
  api_key: ""                    # Empty = env var or not needed for local
  model: "qwen/qwen3-coder-30b"

llm:
  profile: "auto"                # auto | compact | default
                                 # auto: compact if max_context_tokens <= 8192
                                 # compact: short prompt, 5 core tools, no memory/skills
                                 # default: full prompt, all tools, all injections

security:
  allowed_path_prefix: ""        # empty = unrestricted (blocklist only); set "Assets/" for Unity
  blocked_prefixes:
    - "C:/Windows"
    - "C:/Program Files"
    - "/etc"
    - "/bin"
    - "/usr"
    - ".git"
  write_blocked_prefixes:
    - ".clu"

tools:
  enabled: [think, read_file, write_file, list_files, search_in_files,
            memory, delegate, manage_schedules, manage_context]

validation:
  enabled: false                 # Set true + validator: "csharp" for C# projects

heartbeat:
  checks: [new_files, todo_markers, large_files]
  auto_fix_on_error: true
```

See `config/profiles/` for complete examples (Unity, Python).

## 7. Web Dashboard

**URL**: `http://localhost:8080`

2-column responsive layout:
- **Center**: real-time chat streaming (tool calls, results, responses)
- **Right panel**: 8-tab dashboard

### Tabs

| Tab | Content |
|-----|---------|
| Logs | Agent execution logs with filter (All/Tool/Warn/Err) |
| Tasks | Task queue with status badges, retry/cancel, quick enqueue |
| Sched | Schedule CRUD with enable/disable, trigger, cron preview |
| HB | Heartbeat pulse indicator, check results, manual trigger |
| Alerts | Notification center with read/unread tracking, badges |
| Mem | Memory browser (knowledge categories) with inline editing |
| Costs | Token consumption tracking (by session, aggregated) |
| Skills | Loaded skills list (tier badge, tools, checks), reload, per-skill tests |
| Context | User context rules with role scopes (always/coder/reviewer/tester), add/toggle/delete |

**Chat page** also includes a collapsible session strip (rename, resume, delete)
and feature toggles / project settings are in the Config page.

### REST API (40+ endpoints)

```
POST /api/tasks                  Enqueue a task (with optional role)
GET  /api/tasks                  List all tasks
POST /api/tasks/{id}/cancel      Cancel a task
POST /api/tasks/{id}/retry       Retry a failed task

GET  /api/heartbeat              Heartbeat status + last results
POST /api/heartbeat/trigger      Manual heartbeat trigger

GET  /api/schedules              List schedules
POST /api/schedules              Create schedule
PUT  /api/schedules/{id}         Update schedule
DELETE /api/schedules/{id}       Delete schedule
POST /api/schedules/{id}/toggle  Enable/disable

GET  /api/status                 Provider + project status
POST /api/project                Set project path

POST /api/config/provider        Configure LLM provider
POST /api/config/profile         Switch LLM profile (auto/compact/default)
POST /api/config/features        Toggle features (heartbeat, validation, skills…)
GET  /api/models                 List available models
POST /api/config/budget          Modify budget limits at runtime

GET  /api/sessions               Saved sessions list
GET  /api/sessions/{id}          Load a session
DELETE /api/sessions/{id}        Delete a session
POST /api/sessions/{id}/rename   Rename a session

GET  /api/alerts                 List alerts
POST /api/alerts/{id}/read       Mark alert read
POST /api/alerts/read-all        Mark all read

GET  /api/memory                 Memory overview
GET  /api/memory/{category}      Get knowledge category
PUT  /api/memory/{category}      Update knowledge category

GET  /api/costs                  Aggregated token costs
POST /api/decompose-and-enqueue  Decompose + enqueue sub-tasks
GET  /api/roles                  List agent roles

POST /api/webhooks/github        GitHub webhook receiver
POST /api/webhooks/generic       Generic webhook receiver
POST /api/stop                   Stop running agent

GET  /api/skills                 List all loaded skills with status
GET  /api/skills/{name}          Skill details (tools, checks, requirements)
POST /api/skills/reload          Hot-reload all skills from disk
POST /api/skills/{name}/test     Run declarative tests for a specific skill
POST /api/skills/test/all        Run all skill tests

GET  /api/context                List all context items
POST /api/context                Create a context item (name, content, scope)
PUT  /api/context/{id}           Update a context item (enabled, scope, content)
DELETE /api/context/{id}         Delete a context item
```

### WebSocket

```
WS /ws/agent
  Send:    {action: "run_task", task, project, resume_session?}
  Receive: agent_start, iteration, tool_call, tool_result,
           agent_response, agent_done, warning, error, info
```

## 8. Skills System

The skills system is a 3-tier extensibility layer that lets contributors add tools, checks, prompts,
and templates without modifying CLU's core code.

### Skill Package Layout

```
my-skill/
  skill.yaml          # Manifest (REQUIRED) — never injected into LLM context
  prompt.md           # Optional context injected into system prompt (lazy, budgeted)
  tools/              # Python modules extending BaseTool
  checks/             # Python modules with run(project_path) → CheckResult
  templates/          # Markdown task templates for the scheduler
```

### 4-Tier Discovery (priority: project > user > registry > bundled)

| Tier | Location | Trust |
|------|----------|-------|
| bundled | `skills/bundled/` | Shipped with CLU |
| registry | `~/.clu/registry-cache/` | Community-sourced, prompt-only (no Python modules) |
| user | `~/.clu/skills/` | Per-user across all projects |
| project | `<project>/.clu/skills/` | Highest priority — per-project overrides |

If two tiers define a skill with the same name, the higher-priority tier wins.

### 4th Tier: Community Registry (optional)

CLU can pull prompt-only skills from a public GitHub registry:

| Tier | Location | Notes |
|------|----------|-------|
| registry | `~/.clu/registry-cache/` | Downloaded from community GitHub repo |

- **Registry**: `https://github.com/Continuous-Learning-Utility/clu-skills`
- **Content**: `skill.yaml` + `prompt.md` only (no Python modules — no code execution risk)
- **Security CI**: Every PR to the registry runs `scripts/validate_skill.py` (GitHub Actions)
  with the same secret-scanning, injection-detection, and SHA-256 checks as the local SkillLoader
- **Branch protection**: `main` requires the `validate` check to pass before merge

```yaml
skills:
  registry_url: "https://github.com/Continuous-Learning-Utility/clu-skills"
  registry_sync_enabled: false     # set true to auto-pull
  registry_sync_interval: 86400    # seconds between syncs (24h)
```

### Security

- **Secret scanning**: 8 regex patterns (OpenAI `sk-`, GitHub `ghp_/ghs_`, AWS `AKIA`,
  Google `AIza`, Bearer tokens, generic `api_key=`…) checked against all skill files
  before any module import. Skill rejected if matched.
- **Prompt injection detection**: 8 patterns (`ignore previous instructions`, `act as`,
  `you are now`, `DAN`, etc.) checked against `prompt.md`. Injections filtered out.
- **SHA-256 integrity**: optional `integrity:` section in `skill.yaml` maps files to
  expected hashes. Mismatch → `SkillIntegrityError` → skill not loaded.
- **`skill.yaml` is never injected into LLM context** — only `prompt.md` is, selectively.

### Prompt Injection (contextual + budgeted)

Skills with a `prompt:` section are lazy-loaded. Before each agent run, `SkillManager`
checks `is_prompt_relevant(task_text)` (keyword matching) and injects only relevant
skill prompts. Two budget levels apply:
- **Per-skill budget** (`budget:` in `prompt:` section, default 3000 chars)
- **Global budget** (`skills.prompt_budget` in config, default 12K chars)

### Bundled Skills

| Skill | Type | Trigger keywords |
|-------|------|-----------------|
| `unity-support` | prompt + check | unity, csharp, monobehaviour, compile |
| `todo-tracker` | prompt + check | todo, fixme, hack, technical debt |
| `code-conventions` | prompt only | refactor, clean, naming, readability |

### CLI Commands

```bash
python main.py --skills list     # List all discovered skills
python main.py --skills test     # Run all declarative skill tests
```

### Config Fields

```yaml
skills:
  enabled: true              # Set false to disable the entire system (zero-cost)
  user_dir: ""               # Override ~/.clu/skills/
  project_dir: ""            # Override .clu/skills/ relative to --project
  prompt_budget: 12000       # Global max chars injected per agent run
```

## 10. Notifications & Integrations

### Notifications
- **Desktop**: win10toast (Windows), osascript (macOS), notify-send (Linux)
- **Discord**: webhook with embedded messages (color-coded by level)
- **Slack**: webhook with emoji-prefixed text

### GitHub Webhooks
- Issues opened with label `ai-agent` → auto-enqueued as tasks
- Push events filtering source files → auto-review tasks
- HMAC-SHA256 signature verification

## 11. Dependencies

**Required:**
- Python 3.13+
- An LLM provider (local or cloud)

**Optional:**
- .NET SDK 8.0+ (for C# validation only)

**Python packages:**
```
openai>=1.12.0
pyyaml>=6.0
jsonschema>=4.20.0
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
websockets>=14.0
anthropic>=0.50.0       # optional, for Claude
google-genai>=1.0.0     # optional, for Gemini
```

## 12. Getting Started

```bash
# Clone and setup
git clone https://github.com/SamDreamsMaker/Continuous-Learning-Utility.git
cd Continuous-Learning-Utility
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Launch dashboard
python main.py --web --project "/path/to/your/project"

# Or use a specific config profile
python main.py --web --config config/profiles/python.yaml

# Start daemon
python main.py --daemon start

# Run tests
python -m pytest tests/ -v    # 450 tests
```

---
*End of architecture reference.*
