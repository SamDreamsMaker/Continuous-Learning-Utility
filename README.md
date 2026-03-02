<p align="center">
  <h1 align="center">CLU</h1>
  <p align="center"><strong>Continuous Learning Utility</strong></p>
  <p align="center">
    An autonomous, self-healing AI coding agent that runs 24/7.<br>
    Local-first. Any language. Any LLM.
  </p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> &middot;
    <a href="#features">Features</a> &middot;
    <a href="#architecture">Architecture</a> &middot;
    <a href="#configuration">Configuration</a> &middot;
    <a href="#web-dashboard">Dashboard</a>
  </p>
</p>

---

## What is CLU?

CLU is an autonomous AI coding agent with a persistent daemon, task queue, and web dashboard. It follows a **THINK → ACT → OBSERVE** loop to complete software engineering tasks — writing code, fixing bugs, reviewing files, generating tests — with full sandbox security and automatic validation.

It works with **any language and framework** out of the box. Point it at your project, configure a YAML profile, and let it work.

```
You: "Add user authentication with JWT tokens"
CLU: thinks → reads existing code → plans the implementation → writes files → done
```

## Features

**Core Agent**
- Autonomous THINK → ACT → OBSERVE execution loop
- 13 LLM tools: read, write, search, validate, delegate, manage schedules, manage context, and more
- Anti-loop detection with 3-level escalation (text warning → write mode → tool removal)
- Session persistence and crash recovery with checkpointing
- Automatic file backup before every write

**24/7 Daemon**
- SQLite task queue with priority, retry, and dead letter handling
- Heartbeat monitoring: compile errors, new files, TODO markers, large files
- Cron-like task scheduling with custom parser (no external deps)
- Auto-fix: detects issues and enqueues repair tasks autonomously

**Multi-Agent**
- Role-based execution: `coder`, `reviewer`, `tester` — each with restricted tool access
- LLM-powered task decomposition into prioritized sub-tasks
- In-agent delegation via the `delegate` tool

**Multi-Provider LLM**
- **Local**: LM Studio, Ollama, vLLM (OpenAI-compatible API)
- **Cloud**: Anthropic Claude, Google Gemini, OpenAI
- Resilient provider with retry, circuit breaker, and failover
- Hot-swap provider and model from the dashboard

**Skills System**
- 4-tier extensibility: bundled, user (`~/.clu/skills/`), project (`.clu/skills/`), registry (`~/.clu/registry-cache/`)
- Community registry: `https://github.com/Continuous-Learning-Utility/clu-skills`
- Contextual prompt injection — only relevant skills are loaded, budget-limited
- SHA-256 integrity checks + secret scanning + prompt injection detection
- Declarative tests per skill (`skill.yaml`), CLI: `python main.py --skills test`
- Bundled: `unity-support`, `todo-tracker`, `code-conventions`

**Web Dashboard**
- Real-time streaming via WebSocket
- 9-tab panel: Logs, Tasks, Schedules, Heartbeat, Alerts, Memory, Costs, Skills, Context
- 40+ REST API endpoints
- Task queue management, schedule CRUD, memory browser, skills viewer

**Integrations**
- GitHub webhooks (issues → tasks, push → auto-review)
- Notifications: desktop (Windows/macOS/Linux), Discord, Slack
- Unity Editor plugin (optional, for C# projects)

**Security**
- Configurable sandbox: optional path prefix + blocklist + write-only blocklist
- Default: unrestricted (no prefix) with OS system dirs blocked (C:/Windows, /etc, /bin…)
- Write-blocked dirs (`.clu/`) prevent CLU from injecting malicious skill modules
- Anti-traversal and anti-symlink protection
- Budget limits: max iterations, max tokens, context window cap
- Context overflow prevention: auto-trims prompt sections when exceeding model context window
- LLM profiles (`auto`/`compact`/`default`): adapts prompt size, tools, and thresholds for small local models

## Quick Start

### Prerequisites

- **Python 3.13+**
- **An LLM provider** — either a local server ([LM Studio](https://lmstudio.ai), Ollama) or a cloud API key

### Setup

```bash
# Clone the repository
git clone https://github.com/SamDreamsMaker/Continuous-Learning-Utility.git
cd Continuous-Learning-Utility

# Option A: Automated setup (Windows)
setup.bat

# Option B: Manual setup (any OS)
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

### Launch

```bash
# Web dashboard (recommended)
python main.py --web
# → opens http://localhost:8080

# With a pre-loaded project
python main.py --web --project "/path/to/your/project"

# Single task (CLI)
python main.py --project "/path/to/project" --task "Fix the login bug"

# Interactive REPL
python main.py --project "/path/to/project" --interactive

# 24/7 Daemon
python main.py --daemon start
python main.py --daemon status
python main.py --daemon stop
```

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Web Dashboard                       │
│              FastAPI + WebSocket (:8080)                  │
│     ┌──────────────────────┬──────────────────────┐       │
│     │       Chat           │        Panel         │       │
│     │  (Stream / Tasks)    │       (8 tabs)       │       │
│     └──────────────────────┴──────────────────────┘       │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│                    Orchestrator                           │
│  ┌─────────────┐  ┌──────────┐  ┌─────────────────────┐ │
│  │ AgentRunner  │  │  Budget  │  │  Message History    │ │
│  │ (async loop) │  │ Tracker  │  │  + Loop Detection   │ │
│  └──────┬──────┘  └──────────┘  └─────────────────────┘ │
│         │                                                │
│  ┌──────▼──────┐  ┌──────────┐  ┌─────────────────────┐ │
│  │    Tool     │  │ Session  │  │     Resilient       │ │
│  │ Dispatcher  │  │ Manager  │  │     Provider        │ │
│  └──────┬──────┘  └──────────┘  └──────────┬──────────┘ │
└─────────┼──────────────────────────────────┼─────────────┘
          │                                  │
┌─────────▼──────────┐          ┌────────────▼─────────────┐
│   12 LLM Tools     │          │    LLM Providers         │
│                     │          │                          │
│  think              │          │  OpenAI-compatible       │
│  read_file          │          │   (LM Studio, Ollama,    │
│  write_file         │          │    vLLM, OpenAI)         │
│  list_files         │          │                          │
│  search_in_files    │          │  Anthropic (Claude)      │
│  validate_csharp    │          │  Google (Gemini)         │
│  unity_logs         │          │                          │
│  memory             │          └──────────────────────────┘
│  delegate           │
│  manage_schedules   │
└─────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    24/7 Daemon                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐ │
│  │  Task      │  │ Heartbeat  │  │    Scheduler       │ │
│  │  Queue     │  │ Manager    │  │    (cron-like)      │ │
│  │ (SQLite)   │  │            │  │                    │ │
│  └────────────┘  └─────┬──────┘  └────────────────────┘ │
│                        │                                 │
│                  ┌─────▼──────────────────────┐          │
│                  │  Checks                    │          │
│                  │  compile | new_files |      │          │
│                  │  todo_markers | large_files │          │
│                  └────────────────────────────┘          │
│                                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐ │
│  │ Webhooks   │  │ Notifiers  │  │     Alerts         │ │
│  │ (GitHub)   │  │ (Desktop/  │  │  (persistence)     │ │
│  │            │  │ Discord/   │  │                    │ │
│  │            │  │ Slack)     │  │                    │ │
│  └────────────┘  └────────────┘  └────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

## Configuration

CLU uses a single YAML configuration file. The default config is generic (any language), with optional profiles for specific frameworks like Unity/C#.

### `config/default.yaml`

```yaml
project:
  name: "generic"
  language: "any"
  file_extensions: []                   # empty = scan all files
  source_dir: ""                        # empty = project root
  framework: "generic"

api:
  provider: "openai_compat"           # openai_compat | anthropic | google
  base_url: "http://localhost:1234/v1"
  api_key: ""
  model: "qwen/qwen3-coder-30b"

llm:
  temperature: 0
  seed: 42
  max_tokens: 4096
  stream: false                       # MUST be false for tool calling
  profile: "auto"                     # auto | compact | default

budget:
  max_iterations: 50
  max_total_tokens: 500000
  max_context_tokens: 32000

security:
  allowed_path_prefix: ""             # empty = unrestricted (blocklist only); set "Assets/" for Unity
  blocked_prefixes:
    - "C:/Windows"
    - "C:/Program Files"
    - "/etc"
    - "/bin"
    - "/usr"
    - ".git"
  write_blocked_prefixes:
    - ".clu"
  max_file_read_size: 102400          # 100 KB
  max_file_write_size: 51200          # 50 KB

tools:
  enabled:
    - think
    - read_file
    - write_file
    - list_files
    - search_in_files
    - memory
    - delegate
    - manage_schedules
    - manage_context
    # Optional:
    # - validate_csharp
    # - unity_logs
```

### Example: Python Project

```yaml
# config/profiles/python.yaml
project:
  name: "python"
  language: "python"
  file_extensions: [".py"]
  source_dir: "src/"
  framework: "generic"

security:
  blocked_prefixes: [".git", ".venv", "__pycache__", "dist"]

validation:
  enabled: false

tools:
  enabled: [think, read_file, write_file, list_files, search_in_files, memory, delegate, manage_schedules]
```

Load a profile with:

```bash
python main.py --web --config config/profiles/python.yaml
```

## Web Dashboard

The dashboard runs at `http://localhost:8080` and provides a 2-column layout:

| Section | Description |
|---------|-------------|
| **Chat** | Real-time agent execution stream (tool calls, results, responses) |
| **Panel** | 9-tab dashboard (Logs, Tasks, Schedules, Heartbeat, Alerts, Memory, Costs, Skills, Context) |

### Key Capabilities

- **Task Queue**: Enqueue, cancel, retry tasks with priority levels
- **Schedules**: Create cron-based recurring tasks (e.g., compile checks every 5 min)
- **Heartbeat**: See live health checks — compile errors, TODO markers, large files
- **Alerts**: Notification center with read/unread tracking
- **Memory**: Browse and edit the agent's persistent knowledge base
- **Costs**: Track token consumption across sessions
- **Skills**: View loaded skills, trigger reload, run per-skill tests
- **Context**: Manage persistent context rules (scope: always / coder / reviewer / tester) injected into every agent run
- **Provider Config**: Switch LLM provider/model on the fly
- **Feature Toggles**: Enable/disable heartbeat, validation, skills, auto-fix, auto-generate from the UI
- **Project Settings**: Configure source directory, language, file extensions at runtime
- **Sessions**: Collapsible session picker in Chat with inline rename and resume

### REST API

40+ endpoints available. Key examples:

```
POST /api/tasks               Enqueue a task
GET  /api/tasks               List all tasks
GET  /api/heartbeat           Heartbeat status
POST /api/heartbeat/trigger   Manual heartbeat
GET  /api/schedules           List schedules
POST /api/config/provider     Switch LLM provider
POST /api/config/features     Toggle features (heartbeat, validation, skills…)
POST /api/config/profile      Switch LLM profile (auto/compact/default)
POST /api/sessions/{id}/rename  Rename a session
GET  /api/models              List available models
POST /api/webhooks/github     GitHub webhook receiver
WS   /ws/agent                WebSocket for streaming execution
```

## Daemon Mode

The daemon runs continuously, polling the task queue and performing autonomous maintenance.

```
while running:
  1. Dequeue highest-priority task → execute with AgentRunner
  2. If queue empty:
     a. Run heartbeat checks (compile, new files, TODOs, large files)
     b. Auto-enqueue fixes for detected issues
     c. Run scheduler tick (fire due cron jobs)
  3. Send notifications (desktop / Discord / Slack)
  4. Sleep 5s → repeat
```

### Scheduled Tasks

Defined in `config/schedules.yaml`:

```yaml
schedules:
  - id: compile_check
    cron: "*/5 * * * *"        # every 5 minutes
    task_template: auto_fix_compile
    enabled: true
    priority: 10

  - id: daily_review
    cron: "0 9 * * 0-4"       # 9 AM weekdays
    task_template: code_review
    enabled: false
```

The agent can also manage its own schedules at runtime via the `manage_schedules` tool.

## Multi-Agent Roles

CLU supports role-based task execution with restricted tool access:

| Role | Access | Use Case |
|------|--------|----------|
| `coder` | All tools | Write code, fix bugs, refactor |
| `reviewer` | Read-only | Code review, audit, analysis |
| `tester` | Read + write tests | Generate test files |

Complex tasks can be decomposed into sub-tasks with assigned roles:

```
POST /api/decompose-and-enqueue
{
  "task": "Refactor the authentication system and add tests"
}
```

CLU's LLM splits this into prioritized sub-tasks (e.g., refactor → review → test), each executed by the appropriate role.

## LLM Tools

| # | Tool | Description |
|---|------|-------------|
| 1 | `think` | Forces the LLM to articulate reasoning before acting |
| 2 | `read_file` | Read file contents with line numbers |
| 3 | `write_file` | Full write or incremental patches with automatic backup |
| 4 | `list_files` | Directory listing with glob pattern support |
| 5 | `search_in_files` | Regex search across project files |
| 6 | `validate_csharp` | C# syntax validation via dotnet build (optional) |
| 7 | `unity_logs` | Read Unity Editor logs (optional) |
| 8 | `memory` | Read/write persistent knowledge (conventions, patterns, issues) |
| 9 | `delegate` | Enqueue sub-tasks for other agent roles |
| 10 | `manage_schedules` | CRUD operations on cron schedules at runtime |
| 11 | `manage_context` | List/add/disable/delete user context items (with role scope) |

## Integrations

### GitHub Webhooks

Configure a webhook pointing to `http://your-server:8080/api/webhooks/github`:

- **Issues**: Issues labeled `ai-agent` are auto-enqueued as tasks
- **Push**: Commits touching source files trigger automatic review

Set `webhooks.github_secret` in config for HMAC-SHA256 signature verification.

### Notifications

```yaml
notifications:
  desktop: true              # OS-native (Windows toast / macOS / Linux)
  discord_webhook: "https://discord.com/api/webhooks/..."
  slack_webhook: "https://hooks.slack.com/services/..."
```

### Unity Editor Plugin

For Unity/C# projects, an optional Editor plugin (`unity_plugin/AgentBridge.cs`) provides a GUI window inside Unity to communicate with CLU via HTTP.

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# 450 tests across 22 test files
# Covers: agent, daemon, heartbeat, integrations, memory,
#         multi-agent, providers, resilience, sandbox,
#         scheduler, tools, manage_schedules,
#         skill_manifest, skill_loader, skill_manager,
#         skill_integrations, skill_config, skill_test_runner,
#         outcome_tracker, pattern_analyzer, skill_generator, registry

# Skills CLI
python main.py --skills list     # List all loaded skills
python main.py --skills test     # Run declarative skill tests
```

## Project Structure

```
CLU/
├── main.py                    # CLI entry point
├── config/
│   ├── default.yaml           # Main configuration
│   ├── schedules.yaml         # Cron schedule definitions
│   └── profiles/              # Language/framework profiles
│       ├── unity.yaml
│       └── python.yaml
├── orchestrator/              # Core agent engine
│   ├── runner.py              # AgentRunner (async execution loop)
│   ├── config.py              # AgentConfig dataclass
│   ├── providers/             # LLM provider abstraction
│   ├── resilience.py          # Retry + circuit breaker
│   ├── decomposer.py          # Task decomposition
│   └── memory.py              # Persistent memory
├── daemon/                    # 24/7 daemon subsystem
│   ├── daemon.py              # Main daemon loop
│   ├── task_queue.py          # SQLite task queue
│   ├── heartbeat.py           # Health monitoring
│   ├── scheduler.py           # Cron scheduler
│   ├── checks/                # Heartbeat check plugins
│   └── webhooks.py            # GitHub + generic webhooks
├── skills/                    # Extensible skills system
│   ├── manifest.py            # SkillManifest (SHA-256, keywords, budget)
│   ├── loader.py              # 3-tier discovery + security scanning
│   ├── manager.py             # Tool registration + prompt injection
│   ├── test_runner.py         # Declarative test execution
│   └── bundled/               # Skills shipped with CLU
│       ├── unity-support/     # Unity/C# guidelines + compile check
│       ├── todo-tracker/      # TODO/FIXME scanner
│       └── code-conventions/  # Generic code quality guidelines
├── tools/                     # 13 LLM-callable tools
├── sandbox/                   # Path validation + backups
├── validation/                # C# validator (optional)
├── web/                       # Dashboard (FastAPI + vanilla JS)
├── prompts/                   # System prompts + role definitions
│   ├── profiles/              # Language-specific prompts
│   ├── roles/                 # coder / reviewer / tester
│   └── task_templates/        # Reusable task templates
├── docs/                      # In-depth architecture reference
├── tests/                     # 387 unit tests (pytest)
└── unity_plugin/              # Unity Editor integration (optional)
```

For detailed internals, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

| Dependency | Required | Notes |
|-----------|----------|-------|
| Python 3.13+ | Yes | Auto-installed by `setup.bat` on Windows |
| LLM provider | Yes | Local (LM Studio, Ollama) or cloud (Anthropic, Google, OpenAI) |
| .NET SDK 8.0+ | No | Only for C# validation |
| Unity Editor | No | Only for Unity DLL references |

### Python Packages

```
openai>=1.12.0
pyyaml>=6.0
jsonschema>=4.20.0
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
websockets>=14.0
anthropic>=0.50.0          # optional
google-genai>=1.0.0        # optional
```

## Cross-Platform

CLU runs on **Windows**, **Linux**, and **macOS** without OS-specific dependencies.

| | Windows | Linux / macOS |
|---|---------|---------------|
| Setup | `setup.bat` | `python -m venv venv && pip install -r requirements.txt` |
| Dashboard | `run.bat` | `python main.py --web` |
| Daemon | `run_daemon.bat` | `./run_daemon.sh` |
| Notifications | Win10 toast | `notify-send` / `osascript` |

## License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
  <strong>CLU</strong> — Continuous Learning Utility<br>
  Built with autonomy in mind.
</p>
