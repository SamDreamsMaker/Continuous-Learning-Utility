"""Web server: FastAPI + WebSocket for the CLU dashboard."""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator.config import AgentConfig, load_config
from orchestrator.providers.factory import create_provider, PROVIDER_TYPES
from orchestrator.providers.base import LLMProvider
from orchestrator.session import SessionManager
from orchestrator.runner import AgentRunner
from orchestrator.events import AgentEvent
from daemon.task_queue import TaskQueue, TaskStatus
from daemon.heartbeat import HeartbeatManager, HeartbeatConfig
from daemon.alerts import AlertManager
from daemon.scheduler import TaskScheduler
from daemon.webhooks import WebhookHandler
from daemon import service as daemon_service
from skills.loader import SkillLoader
from skills.manager import SkillManager
from skills.state import SkillStateStore
from orchestrator.context_store import ContextStore
from modules.manager import ModuleManager

logger = logging.getLogger(__name__)

app = FastAPI(title="CLU")

# Serve static files
WEB_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.dirname(WEB_DIR)

# Global state
_config: AgentConfig | None = None
_project_path: str | None = None
_provider: LLMProvider | None = None
_skill_manager: SkillManager | None = None
_skill_state: SkillStateStore | None = None
_context_store: ContextStore | None = None
_module_manager: ModuleManager | None = None


def get_config() -> AgentConfig:
    global _config
    if _config is None:
        config_path = os.path.join(AGENT_DIR, "config", "default.yaml")
        load_config(config_path)
        _config = AgentConfig.from_yaml(config_path)
    return _config


def get_provider() -> LLMProvider:
    """Get or create the current LLM provider."""
    global _provider
    if _provider is None:
        config = get_config()
        _provider = create_provider(
            config.provider, config.api_base, config.api_key, config.model
        )
    return _provider


def set_provider(provider: LLMProvider):
    global _provider
    _provider = provider


def get_project_path() -> str:
    global _project_path
    if _project_path is None:
        _project_path = os.environ.get("AGENT_PROJECT_PATH", os.getcwd())
    return _project_path


def set_project_path(path: str):
    global _project_path
    _project_path = path


# ---- REST endpoints ----

@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/status")
async def status():
    config = get_config()
    project = get_project_path()

    # Test LLM provider connection
    provider_ok = False
    provider_name = config.provider
    model_name = config.model
    provider_models = []
    try:
        provider = get_provider()
        result = await asyncio.to_thread(provider.test_connection)
        provider_ok = result.get("ok", False)
        provider_name = provider.provider_name
        model_name = provider.model_name
        provider_models = result.get("models", [])
    except Exception:
        pass

    # Check project validity
    project_ok = False
    source_file_count = 0
    source_dir = config.project_source_dir.strip("/").strip("\\")
    file_exts = config.project_file_extensions
    if project and os.path.isdir(project):
        scan_dir = os.path.join(project, source_dir) if source_dir else project
        if os.path.isdir(scan_dir):
            project_ok = True
            for root, dirs, files in os.walk(scan_dir):
                source_file_count += sum(
                    1 for f in files
                    if not file_exts or any(f.endswith(ext) for ext in file_exts)
                )

    return {
        "provider": {
            "connected": provider_ok,
            "type": config.provider,
            "name": provider_name,
            "model": model_name,
            "base_url": config.api_base,
            "has_key": bool(config.api_key),
            "models": provider_models,
        },
        "project": {
            "path": project,
            "valid": project_ok,
            "source_files": source_file_count,
            "cs_files": source_file_count,  # backward compat
        },
        "config": {
            "max_iterations": config.max_iterations,
            "max_total_tokens": config.max_total_tokens,
            "max_context_tokens": config.max_context_tokens,
            "temperature": config.temperature,
            "llm_profile": config.llm_profile,
            "project_name": config.project_name,
            "project_source_dir": config.project_source_dir,
            "project_language": config.project_language,
            "validation_enabled": config.validation_enabled,
            "heartbeat_enabled": config.heartbeat_enabled,
            "heartbeat_auto_fix_on_error": config.heartbeat_auto_fix_on_error,
            "skills_enabled": config.skills_enabled,
            "skills_auto_generate": config.skills_auto_generate,
        },
    }


# ---- Session endpoints ----

_session_mgr = SessionManager(os.path.join(AGENT_DIR, "sessions"))


@app.get("/api/sessions")
async def list_sessions():
    project = get_project_path()
    sessions = _session_mgr.list_sessions(project_path=project or None)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    data = _session_mgr.load(session_id)
    if data is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return data


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = _session_mgr.delete(session_id)
    return {"deleted": ok}


@app.post("/api/sessions/{session_id}/rename")
async def rename_session(session_id: str, body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    ok = _session_mgr.rename(session_id, name)
    if not ok:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"ok": True, "name": name}


@app.post("/api/config/features")
async def update_features(body: dict):
    """Update feature toggles and project settings at runtime."""
    config = get_config()
    ALLOWED = {
        "project_name", "project_source_dir", "project_language",
        "project_file_extensions",
        "validation_enabled", "heartbeat_enabled",
        "heartbeat_auto_fix_on_error", "heartbeat_interval",
        "heartbeat_large_file_threshold",
        "skills_enabled", "skills_auto_generate",
        "skills_registry_sync_enabled",
        "max_context_tokens",
    }
    updated = {}
    for key, value in body.items():
        if key in ALLOWED and hasattr(config, key):
            expected_type = type(getattr(config, key))
            if expected_type == bool:
                value = bool(value)
            elif expected_type == int:
                value = int(value)
            elif expected_type == list and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            setattr(config, key, value)
            updated[key] = getattr(config, key)
    return {"ok": True, "updated": updated}


@app.post("/api/config/profile")
async def update_llm_profile(body: dict):
    """Update the LLM profile at runtime (auto/compact/default)."""
    config = get_config()
    profile = body.get("profile", "").strip()
    if profile not in ("auto", "compact", "default"):
        return JSONResponse({"error": f"Invalid profile: {profile}"}, status_code=400)
    config.llm_profile = profile
    return {"ok": True, "llm_profile": profile}


@app.post("/api/config/budget")
async def update_budget(body: dict):
    """Update budget limits at runtime."""
    config = get_config()
    if "max_iterations" in body:
        config.max_iterations = int(body["max_iterations"])
    if "max_total_tokens" in body:
        config.max_total_tokens = int(body["max_total_tokens"])
    return {"ok": True, "max_iterations": config.max_iterations, "max_total_tokens": config.max_total_tokens}


# ---- Provider endpoints ----

@app.get("/api/provider")
async def get_provider_config():
    """Get current provider configuration (without exposing API key)."""
    config = get_config()
    return {
        "provider": config.provider,
        "base_url": config.api_base,
        "model": config.model,
        "has_key": bool(config.api_key),
        "available_types": PROVIDER_TYPES,
    }


@app.post("/api/provider")
async def update_provider(body: dict):
    """Change provider configuration at runtime."""
    config = get_config()

    provider_type = body.get("provider", config.provider)
    base_url = body.get("base_url", config.api_base)
    api_key = body.get("api_key", config.api_key)
    model = body.get("model", config.model)

    try:
        new_provider = create_provider(provider_type, base_url, api_key, model)
        # Update config
        config.provider = provider_type
        config.api_base = base_url
        config.api_key = api_key
        config.model = model
        # Update global provider
        set_provider(new_provider)
        return {
            "ok": True,
            "provider": provider_type,
            "model": model,
            "name": new_provider.provider_name,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/provider/test")
async def test_provider(body: dict):
    """Test a provider connection without changing the active one."""
    provider_type = body.get("provider", "openai_compat")
    base_url = body.get("base_url", "http://localhost:1234/v1")
    api_key = body.get("api_key", "")
    model = body.get("model", "")

    try:
        provider = create_provider(provider_type, base_url, api_key, model)
        result = await asyncio.to_thread(provider.test_connection)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/provider/models")
async def list_provider_models():
    """List models available on the current provider."""
    try:
        provider = get_provider()
        models = await asyncio.to_thread(provider.list_models)
        return {"ok": True, "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": []}


# ---- Task queue endpoints ----

_task_queue = TaskQueue()


@app.get("/api/tasks")
async def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0):
    """List tasks in the queue."""
    tasks = _task_queue.list_tasks(status=status, limit=limit, offset=offset)
    return {
        "tasks": [
            {
                "id": t.id, "status": t.status, "priority": t.priority,
                "task_type": t.task_type, "payload": t.payload,
                "result": t.result, "error": t.error,
                "created_at": t.created_at, "started_at": t.started_at,
                "completed_at": t.completed_at, "attempts": t.attempts,
                "max_attempts": t.max_attempts, "parent_id": t.parent_id,
            }
            for t in tasks
        ],
        "stats": _task_queue.stats(),
    }


@app.post("/api/tasks")
async def create_task(body: dict):
    """Enqueue a new task."""
    task_text = body.get("task", "").strip()
    project = body.get("project") or get_project_path()
    if not task_text:
        return JSONResponse({"error": "Task text required"}, status_code=400)
    if not project:
        return JSONResponse({"error": "No project path"}, status_code=400)

    metadata = {}
    if body.get("role"):
        metadata["role"] = body["role"]

    task_id = _task_queue.enqueue(
        task_text=task_text,
        project_path=project,
        priority=body.get("priority", 0),
        task_type=body.get("task_type", "manual"),
        metadata=metadata or None,
    )
    return {"ok": True, "task_id": task_id}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    task = _task_queue.get(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    return {
        "id": task.id, "status": task.status, "priority": task.priority,
        "task_type": task.task_type, "payload": task.payload,
        "result": task.result, "error": task.error,
        "created_at": task.created_at, "started_at": task.started_at,
        "completed_at": task.completed_at, "attempts": task.attempts,
        "max_attempts": task.max_attempts, "parent_id": task.parent_id,
    }


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: int):
    ok = _task_queue.cancel(task_id)
    return {"ok": ok}


@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: int):
    ok = _task_queue.retry(task_id)
    return {"ok": ok}


# ---- Daemon endpoints ----

@app.get("/api/daemon/status")
async def daemon_status():
    return daemon_service.status()


@app.post("/api/daemon/start")
async def daemon_start(body: dict | None = None):
    body = body or {}
    return daemon_service.start(
        poll_interval=body.get("poll_interval", 5),
    )


@app.post("/api/daemon/stop")
async def daemon_stop():
    return daemon_service.stop()


# ---- Heartbeat endpoints ----

_heartbeat = HeartbeatManager(queue=_task_queue)


@app.get("/api/heartbeat/status")
async def heartbeat_status():
    return _heartbeat.status


@app.post("/api/heartbeat/tick")
async def heartbeat_tick():
    """Manually trigger a heartbeat tick (useful for testing)."""
    project = get_project_path()
    if not project:
        return JSONResponse({"error": "No project path set"}, status_code=400)

    results = await asyncio.to_thread(_heartbeat.tick, project)
    return {
        "ok": True,
        "results": [
            {
                "check": r.check_name,
                "ok": r.ok,
                "issue_count": r.issue_count,
                "summary": r.summary,
                "issues": r.issues[:10],
            }
            for r in results
        ],
    }


@app.post("/api/heartbeat/config")
async def update_heartbeat_config(body: dict):
    """Update heartbeat settings at runtime."""
    cfg = _heartbeat.config
    if "enabled" in body:
        cfg.enabled = bool(body["enabled"])
    if "interval" in body:
        cfg.interval = int(body["interval"])
    if "auto_fix_compile_errors" in body:
        cfg.auto_fix_compile_errors = bool(body["auto_fix_compile_errors"])
    if "max_auto_tasks_per_hour" in body:
        cfg.max_auto_tasks_per_hour = int(body["max_auto_tasks_per_hour"])
    return {"ok": True, **_heartbeat.status}


# ---- Scheduler endpoints ----

_scheduler = TaskScheduler(queue=_task_queue)


@app.get("/api/schedules")
async def list_schedules():
    return _scheduler.status


@app.post("/api/schedules")
async def create_schedule(body: dict):
    try:
        sched = _scheduler.add_schedule(
            schedule_id=body["id"],
            cron=body["cron"],
            task_template=body["task_template"],
            enabled=body.get("enabled", True),
            priority=body.get("priority", 0),
            description=body.get("description", ""),
            params=body.get("params"),
        )
        return {"ok": True, "schedule": sched.to_dict()}
    except (ValueError, KeyError) as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/api/schedules/{schedule_id}")
async def get_schedule(schedule_id: str):
    sched = _scheduler.get_schedule(schedule_id)
    if not sched:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return sched.to_dict()


@app.put("/api/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, body: dict):
    try:
        sched = _scheduler.update_schedule(schedule_id, **body)
        if not sched:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"ok": True, "schedule": sched.to_dict()}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    return {"ok": _scheduler.delete_schedule(schedule_id)}


@app.post("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str):
    sched = _scheduler.get_schedule(schedule_id)
    if not sched:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _scheduler.update_schedule(schedule_id, enabled=not sched.enabled)
    return {"ok": True, "enabled": not sched.enabled}


@app.post("/api/schedules/{schedule_id}/trigger")
async def trigger_schedule(schedule_id: str):
    """Manually trigger a schedule immediately."""
    sched = _scheduler.get_schedule(schedule_id)
    if not sched:
        return JSONResponse({"error": "Not found"}, status_code=404)
    project = get_project_path()
    if not project:
        return JSONResponse({"error": "No project path set"}, status_code=400)

    task_text = _scheduler._resolve_template(sched)
    task_id = _task_queue.enqueue(
        task_text=task_text,
        project_path=project,
        priority=sched.priority,
        task_type="scheduled",
        metadata={"schedule_id": sched.id, "template": sched.task_template, "manual_trigger": True},
    )
    sched.last_run = time.time()
    sched.run_count += 1
    return {"ok": True, "task_id": task_id}


@app.post("/api/schedules/reload")
async def reload_schedules():
    _scheduler.reload()
    return {"ok": True, "count": len(_scheduler.schedules)}


# ---- Multi-agent endpoints ----

@app.post("/api/decompose")
async def decompose_task(body: dict):
    """Decompose a complex task into sub-tasks using the LLM."""
    from orchestrator.decomposer import TaskDecomposer
    task = body.get("task", "")
    if not task:
        return JSONResponse({"error": "Task is required"}, status_code=400)

    provider = get_provider()
    decomposer = TaskDecomposer(provider)
    sub_tasks = decomposer.decompose(task, context=body.get("context", ""))
    return {
        "ok": True,
        "sub_tasks": [
            {"title": st.title, "description": st.description,
             "role": st.role, "priority": st.priority}
            for st in sub_tasks
        ],
    }


@app.post("/api/decompose-and-enqueue")
async def decompose_and_enqueue(body: dict):
    """Decompose a task and enqueue all sub-tasks."""
    from orchestrator.decomposer import TaskDecomposer
    task = body.get("task", "")
    project = body.get("project") or get_project_path()
    if not task:
        return JSONResponse({"error": "Task is required"}, status_code=400)
    if not project:
        return JSONResponse({"error": "No project path set"}, status_code=400)

    provider = get_provider()
    decomposer = TaskDecomposer(provider)
    sub_tasks = decomposer.decompose(task, context=body.get("context", ""))

    task_ids = []
    for st in sub_tasks:
        full_text = f"[Role: {st.role}] {st.title}\n\n{st.description}"
        tid = _task_queue.enqueue(
            task_text=full_text,
            project_path=project,
            priority=st.priority,
            task_type="manual",
            metadata={"role": st.role, "decomposed_from": task[:200]},
        )
        task_ids.append({"task_id": tid, "title": st.title, "role": st.role})

    return {"ok": True, "enqueued": task_ids}


@app.get("/api/roles")
async def list_roles():
    """List available agent roles."""
    roles_dir = os.path.join(AGENT_DIR, "prompts", "roles")
    roles = []
    if os.path.isdir(roles_dir):
        for f in sorted(os.listdir(roles_dir)):
            if f.endswith(".md"):
                role_id = f[:-3]
                path = os.path.join(roles_dir, f)
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                # Extract first line as title
                title = content.split("\n")[0].replace("#", "").strip()
                roles.append({"id": role_id, "title": title, "file": f})
    return {"roles": roles}


# ---- Alert endpoints ----

_alerts = AlertManager()


@app.get("/api/alerts")
async def list_alerts(unread_only: bool = False, level: str | None = None, limit: int = 50):
    return {
        "alerts": _alerts.list_alerts(unread_only=unread_only, level=level, limit=limit),
        "stats": _alerts.stats(),
    }


@app.post("/api/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int):
    return {"ok": _alerts.mark_read(alert_id)}


@app.post("/api/alerts/read-all")
async def mark_all_alerts_read():
    count = _alerts.mark_all_read()
    return {"ok": True, "count": count}


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int):
    return {"ok": _alerts.delete(alert_id)}


@app.delete("/api/alerts")
async def clear_alerts():
    count = _alerts.clear()
    return {"ok": True, "count": count}


# ---- Webhook endpoints ----

_webhook_handler = WebhookHandler(queue=_task_queue)


@app.post("/api/webhooks/github")
async def github_webhook(request: Request):
    """Receive GitHub webhook events."""
    _webhook_handler.project_path = get_project_path()

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")

    if not _webhook_handler.verify_github_signature(body, signature):
        return JSONResponse({"error": "Invalid signature"}, status_code=401)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    result = _webhook_handler.handle_github(event_type, payload)
    return {
        "ok": result.ok,
        "task_id": result.task_id,
        "message": result.message,
        "skipped": result.skipped,
    }


@app.post("/api/webhooks/generic")
async def generic_webhook(body: dict):
    """Receive a generic webhook with a task payload."""
    _webhook_handler.project_path = get_project_path()
    result = _webhook_handler.handle_generic(body)
    status = 200 if result.ok else 400
    return JSONResponse({
        "ok": result.ok,
        "task_id": result.task_id,
        "message": result.message,
    }, status_code=status)


# ---- Memory endpoints ----

from orchestrator.memory import MemoryManager, CATEGORIES

_memory = MemoryManager()


@app.get("/api/memory")
async def get_memory():
    """Get all memory data for the dashboard."""
    knowledge = {}
    for cat in CATEGORIES:
        knowledge[cat] = _memory.read_knowledge(cat)
        if knowledge[cat].startswith("Unknown category"):
            knowledge[cat] = ""

    return {
        "today": _memory.get_daily_log(),
        "knowledge": knowledge,
        "daily_logs": _memory.list_daily_logs(),
    }


@app.get("/api/memory/{category}")
async def get_memory_category(category: str):
    content = _memory.read_knowledge(category)
    if content.startswith("Unknown category"):
        return JSONResponse({"error": content}, status_code=400)
    return {"category": category, "content": content}


@app.put("/api/memory/{category}")
async def update_memory_category(category: str, body: dict):
    content = body.get("content", "")
    ok = _memory.write_knowledge(category, content)
    if not ok:
        return JSONResponse({"ok": False, "error": f"Invalid category: {category}"}, status_code=400)
    return {"ok": True}


# ---- Costs / Token tracking endpoints ----

@app.get("/api/costs")
async def get_costs():
    """Aggregate token usage from saved sessions."""
    sessions_data = []
    total_tokens = 0
    total_prompt = 0
    total_completion = 0

    sessions_list = _session_mgr.list_sessions()
    for s in sessions_list[:50]:
        sid = s.get("session_id", "")
        session = _session_mgr.load(sid)
        if not session:
            continue

        budget = session.get("budget_state", {})
        tokens = budget.get("total_tokens", 0)
        prompt_t = budget.get("prompt_tokens", 0)
        completion_t = budget.get("completion_tokens", 0)

        total_tokens += tokens
        total_prompt += prompt_t
        total_completion += completion_t

        sessions_data.append({
            "session_id": sid,
            "task": session.get("task", "")[:80],
            "tokens": tokens,
            "prompt_tokens": prompt_t,
            "completion_tokens": completion_t,
            "date": s.get("created", ""),
        })

    return {
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "sessions": sessions_data,
    }


# ---- Context endpoints ----

def get_context_store() -> ContextStore:
    """Get or initialize the global ContextStore for the current project."""
    global _context_store
    if _context_store is None:
        _context_store = ContextStore(project_path=get_project_path() or ".")
    return _context_store


@app.get("/api/context")
async def list_context():
    """List all user context items."""
    store = await asyncio.to_thread(get_context_store)
    return {"items": [i.to_dict() for i in store.list_items()]}


@app.post("/api/context")
async def create_context_item(request: Request):
    """Create a new context item."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    name = (body.get("name") or "").strip()
    content = body.get("content") or ""
    scope = (body.get("scope") or "always").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    store = get_context_store()
    item = store.add_item(name=name, content=content, scope=scope)
    return {"ok": True, "item": item.to_dict()}


@app.put("/api/context/{item_id}")
async def update_context_item(item_id: str, request: Request):
    """Update a context item (name, content, or enabled toggle)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    store = get_context_store()
    updated = store.update_item(item_id, **body)
    if updated is None:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    return {"ok": True, "item": updated.to_dict()}


@app.delete("/api/context/{item_id}")
async def delete_context_item(item_id: str):
    """Delete a context item."""
    store = get_context_store()
    deleted = store.delete_item(item_id)
    if not deleted:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    return {"ok": True}


# ---- Skills endpoints ----

def get_state_store() -> SkillStateStore:
    """Get or initialize the global SkillStateStore."""
    global _skill_state
    if _skill_state is None:
        _skill_state = SkillStateStore()
    return _skill_state


def get_skill_manager() -> SkillManager:
    """Get or initialize the global SkillManager."""
    global _skill_manager
    if _skill_manager is None:
        config = get_config()
        if not config.skills_enabled:
            _skill_manager = SkillManager.empty()
        else:
            proj_skills_dir = None
            project = get_project_path()
            if project and config.skills_project_dir:
                proj_skills_dir = os.path.join(project, config.skills_project_dir)
            elif project:
                candidate = os.path.join(project, ".clu", "skills")
                if os.path.isdir(candidate):
                    proj_skills_dir = candidate

            loader = SkillLoader(
                user_skills_dir=config.skills_user_dir or None,
                project_skills_dir=proj_skills_dir,
            )
            _skill_manager = SkillManager.from_loader(loader, state_store=get_state_store())
    return _skill_manager


@app.get("/api/skills")
async def list_skills():
    """List all loaded skills."""
    try:
        config = get_config()
        mgr = await asyncio.to_thread(get_skill_manager)
        state = get_state_store()
        auto_gen_override = state.get_auto_generate()
        auto_generate = auto_gen_override if auto_gen_override is not None else config.skills_auto_generate
        return {
            "count": mgr.skill_count,
            "skills": mgr.summary(),
            "auto_generate": auto_generate,
        }
    except Exception as e:
        logger.error("Skills load failed: %s", e)
        return {"count": 0, "skills": [], "error": str(e), "auto_generate": False}


@app.get("/api/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get details for a specific skill."""
    mgr = await asyncio.to_thread(get_skill_manager)
    skill = mgr.get_skill(skill_name)
    if skill is None:
        return JSONResponse({"error": f"Skill not found: {skill_name}"}, status_code=404)
    # Return full manifest details
    items = mgr.summary()
    for item in items:
        if item["name"] == skill_name:
            item["test_count"] = len(skill.tests)
            item["checks"] = [c.name for c in skill.checks]
            item["templates"] = [t.name for t in skill.templates]
            item["requirements"] = {
                "os": skill.requirements.os,
                "binaries": skill.requirements.binaries,
                "files": skill.requirements.files,
                "skills": skill.requirements.skills,
            }
            return item
    return JSONResponse({"error": "Skill metadata missing"}, status_code=500)


@app.post("/api/skills/reload")
async def reload_skills():
    """Force reload all skills (clears cache)."""
    global _skill_manager
    _skill_manager = None
    mgr = await asyncio.to_thread(get_skill_manager)
    return {"ok": True, "count": mgr.skill_count, "skills": mgr.summary()}


@app.post("/api/skills/{skill_name}/test")
async def test_skill(skill_name: str):
    """Run declarative tests for a specific skill."""
    from skills.test_runner import SkillTestRunner
    mgr = get_skill_manager()
    skill = mgr.get_skill(skill_name)
    if skill is None:
        return JSONResponse({"error": f"Skill not found: {skill_name}"}, status_code=404)
    runner = SkillTestRunner(project_path=get_project_path() or os.getcwd())
    report = runner.run_skill(skill)
    return report.to_dict()


@app.post("/api/skills/test/all")
async def test_all_skills():
    """Run declarative tests for all loaded skills."""
    from skills.test_runner import SkillTestRunner
    mgr = get_skill_manager()
    runner = SkillTestRunner(project_path=get_project_path() or os.getcwd())
    reports = runner.run_skills(mgr.skills)
    total_passed = sum(r.passed for r in reports)
    total_failed = sum(r.failed for r in reports)
    return {
        "total_passed": total_passed,
        "total_failed": total_failed,
        "success": total_failed == 0,
        "reports": [r.to_dict() for r in reports],
    }


# ---- Secrets (keyring) ----

@app.get("/api/secrets")
async def list_secrets_api():
    """List stored secret names (never exposes values)."""
    from orchestrator.secrets import list_secrets
    return {"secrets": list_secrets()}


@app.post("/api/secrets/{name}")
async def set_secret_api(name: str, body: dict):
    """Store a secret in the OS keyring."""
    from orchestrator.secrets import set_secret
    value = body.get("value", "")
    if not value:
        return JSONResponse({"error": "value is required"}, status_code=400)
    set_secret(name, value)
    return {"ok": True, "name": name}


@app.delete("/api/secrets/{name}")
async def delete_secret_api(name: str):
    """Remove a secret from the OS keyring."""
    from orchestrator.secrets import delete_secret
    delete_secret(name)
    return {"ok": True, "name": name}


# ---- Modules ----

def get_module_manager() -> ModuleManager:
    """Get or initialize the global ModuleManager."""
    global _module_manager
    if _module_manager is None:
        config = get_config()
        if not config.modules_enabled:
            _module_manager = ModuleManager(modules_config={})
        else:
            _module_manager = ModuleManager(
                modules_config=config.modules_config,
                task_queue=_task_queue,
                alert_manager=_alerts,
                project_path=get_project_path(),
                app=app,
            )
            _module_manager.discover(project_path=get_project_path())
    return _module_manager


@app.get("/api/modules")
async def list_modules():
    mgr = get_module_manager()
    return {"modules": mgr.status()}


@app.post("/api/modules/{name}/start")
async def start_module(name: str):
    mgr = get_module_manager()
    ok = await mgr.start_one(name)
    return {"ok": ok, "name": name}


@app.post("/api/modules/{name}/stop")
async def stop_module(name: str):
    mgr = get_module_manager()
    ok = await mgr.stop_one(name)
    return {"ok": ok, "name": name}


@app.post("/api/modules/{name}/toggle")
async def toggle_module(name: str):
    config = get_config()
    mod_cfg = config.modules_config.setdefault(name, {})
    mod_cfg["enabled"] = not mod_cfg.get("enabled", True)
    return {"ok": True, "name": name, "enabled": mod_cfg["enabled"]}


# ---- Skills: pattern analysis & generation ----

@app.get("/api/skills/candidates")
async def list_skill_candidates():
    """Analyze task outcome history and return skill generation candidates."""
    from orchestrator.outcome_tracker import OutcomeTracker
    from skills.pattern_analyzer import PatternAnalyzer, build_existing_skill_keywords

    config = get_config()

    def _analyze():
        tracker = OutcomeTracker()
        outcomes = tracker.load()
        if not outcomes:
            return {"total_outcomes": 0, "candidates": []}

        mgr = get_skill_manager()
        existing_kws = build_existing_skill_keywords(mgr)

        analyzer = PatternAnalyzer(
            outcomes=outcomes,
            existing_skill_keywords=existing_kws,
            min_occurrences=config.skills_generate_min_occurrences,
            min_success_rate=config.skills_generate_min_success_rate,
        )
        candidates = analyzer.find_candidates()
        return {
            "total_outcomes": len(outcomes),
            "candidates": [c.to_dict() for c in candidates],
        }

    return await asyncio.to_thread(_analyze)


@app.post("/api/skills/generate")
async def generate_skill(body: dict):
    """Generate a new skill from a candidate (by index in the candidates list).

    Body: {"candidate_index": 0}
    """
    from orchestrator.outcome_tracker import OutcomeTracker
    from skills.pattern_analyzer import PatternAnalyzer, build_existing_skill_keywords
    from skills.generator import SkillGenerator

    config = get_config()
    candidate_idx = int(body.get("candidate_index", 0))

    def _generate():
        tracker = OutcomeTracker()
        outcomes = tracker.load()
        if not outcomes:
            return {"ok": False, "error": "No outcome data available yet"}

        mgr = get_skill_manager()
        existing_kws = build_existing_skill_keywords(mgr)
        analyzer = PatternAnalyzer(
            outcomes=outcomes,
            existing_skill_keywords=existing_kws,
            min_occurrences=config.skills_generate_min_occurrences,
            min_success_rate=config.skills_generate_min_success_rate,
        )
        candidates = analyzer.find_candidates()
        if not candidates:
            return {"ok": False, "error": "No skill candidates found"}
        if candidate_idx >= len(candidates):
            return {"ok": False, "error": f"Candidate index {candidate_idx} out of range ({len(candidates)} candidates)"}

        candidate = candidates[candidate_idx]

        # Build a minimal provider from current config
        try:
            from orchestrator.providers.factory import create_provider
            provider = create_provider(
                config.provider, config.api_base, config.api_key, config.model,
            )
        except Exception as e:
            return {"ok": False, "error": f"Cannot create LLM provider: {e}"}

        gen = SkillGenerator(provider=provider)
        result = gen.generate(candidate)

        if result.ok:
            # Invalidate SkillManager so the new skill appears immediately
            global _skill_manager
            _skill_manager = None

        return result.to_dict()

    return await asyncio.to_thread(_generate)


# ---- Skills: registry (publish + sync) ----

@app.get("/api/skills/registry/status")
async def registry_status():
    """Return local registry cache state."""
    from skills.registry import get_sync_status
    return await asyncio.to_thread(get_sync_status)


@app.post("/api/skills/registry/sync")
async def registry_sync():
    """Pull new skills from the community registry."""
    config = get_config()

    def _sync():
        from skills.registry import sync as do_sync
        result = do_sync(
            registry_url=config.skills_registry_url,
            skill_manager_invalidate_fn=lambda: globals().update(_skill_manager=None),
        )
        return result.to_dict()

    return await asyncio.to_thread(_sync)


@app.post("/api/skills/{skill_name}/publish")
async def publish_skill(skill_name: str):
    """Publish a locally generated skill to the community registry (creates a PR)."""
    config = get_config()
    if not config.skills_github_token:
        return JSONResponse(
            {"error": "github_token not configured in skills.github_token"},
            status_code=400,
        )

    def _publish():
        from skills.registry import publish as do_publish
        mgr = get_skill_manager()
        skill = mgr.get_skill(skill_name)
        if skill is None:
            return {"ok": False, "error": f"Skill not found: {skill_name}"}
        pr_url = do_publish(
            skill_dir=str(skill.skill_dir),
            skill_name=skill_name,
            github_token=config.skills_github_token,
        )
        return {"ok": True, "pr_url": pr_url}

    try:
        return await asyncio.to_thread(_publish)
    except Exception as e:
        logger.error("Publish skill '%s' failed: %s", skill_name, e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---- Skills: enable / disable ----

@app.post("/api/skills/{skill_name}/enable")
async def enable_skill(skill_name: str):
    """Enable a previously disabled skill."""
    state = get_state_store()
    state.set_enabled(skill_name, True)
    global _skill_manager
    _skill_manager = None
    return {"ok": True, "name": skill_name, "enabled": True}


@app.post("/api/skills/{skill_name}/disable")
async def disable_skill(skill_name: str):
    """Disable a skill (excluded from prompts and tool registration)."""
    state = get_state_store()
    state.set_enabled(skill_name, False)
    global _skill_manager
    _skill_manager = None
    return {"ok": True, "name": skill_name, "enabled": False}


# ---- Skills: auto-generation toggle ----

@app.post("/api/skills/autogen")
async def toggle_autogen(body: dict):
    """Toggle auto-generation of skills at runtime."""
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return JSONResponse({"error": "body must contain {\"enabled\": bool}"}, status_code=400)
    config = get_config()
    config.skills_auto_generate = enabled
    state = get_state_store()
    state.set_auto_generate(enabled)
    return {"ok": True, "auto_generate": enabled}


# ---- Skills: registry browse + install ----

@app.get("/api/skills/registry/available")
async def registry_available():
    """Fetch the registry index and return available skills with install status."""
    config = get_config()

    def _list():
        from skills.registry import list_available as do_list
        skills = do_list(registry_url=config.skills_registry_url)
        return {"skills": skills, "total": len(skills)}

    try:
        return await asyncio.to_thread(_list)
    except Exception as e:
        logger.error("Registry available list failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/skills/registry/install")
async def registry_install(body: dict):
    """Download and install a single skill from the community registry."""
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "body must contain {\"name\": \"skill-name\"}"}, status_code=400)

    config = get_config()

    def _install():
        from skills.registry import install_one
        return install_one(
            name=name,
            registry_url=config.skills_registry_url,
            skill_manager_invalidate_fn=lambda: globals().update(_skill_manager=None),
        )

    try:
        result = await asyncio.to_thread(_install)
        return result
    except Exception as e:
        logger.error("Registry install '%s' failed: %s", name, e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---- WebSocket for agent streaming ----

@app.websocket("/ws/agent")
async def agent_websocket(ws: WebSocket):
    await ws.accept()
    logger.info("WebSocket client connected")

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "run_task":
                task = data.get("task", "")
                project = data.get("project") or get_project_path()
                resume_id = data.get("resume_session")
                if not project:
                    await ws.send_json({"type": "error", "message": "No project path set"})
                    continue
                if not task:
                    await ws.send_json({"type": "error", "message": "No task provided"})
                    continue

                set_project_path(project)
                await _run_agent_streaming(ws, task, project, resume_session_id=resume_id)

            elif action == "rollback":
                await ws.send_json({"type": "info", "message": "Rollback not implemented in this session"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _run_agent_streaming(
    ws: WebSocket, task: str, project_path: str, resume_session_id: str | None = None
):
    """Run the unified AgentRunner, streaming events to the WebSocket."""
    config = get_config()
    provider = get_provider()

    runner = AgentRunner(
        config=config,
        provider=provider,
        project_path=project_path,
        session_mgr=_session_mgr,
        skill_manager=get_skill_manager(),
        context_store=get_context_store(),
    )

    async def on_event(event: AgentEvent):
        await ws.send_json({"type": event.type, **event.data})

    await runner.run(
        task=task,
        on_event=on_event,
        resume_session_id=resume_session_id,
    )


# ---- Module lifecycle events ----

@app.on_event("startup")
async def _startup_modules():
    config = get_config()
    if config.modules_enabled and config.modules_auto_start:
        mgr = get_module_manager()
        results = await mgr.start_all()
        started = sum(1 for v in results.values() if v)
        if started:
            logger.info("Auto-started %d module(s)", started)


@app.on_event("shutdown")
async def _shutdown_modules():
    if _module_manager:
        await _module_manager.stop_all()


# Serve static files (CSS, JS, img)
app.mount("/css", StaticFiles(directory=os.path.join(WEB_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(WEB_DIR, "js")), name="js")
app.mount("/img", StaticFiles(directory=os.path.join(WEB_DIR, "img")), name="img")


def _kill_previous(port: int):
    """Kill any process already listening on the given port (Windows only)."""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="ignore",
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True, timeout=5)
                    print(f"  Killed previous instance (PID {pid})")
                    import time
                    time.sleep(0.5)
                    return True
    except Exception:
        pass
    return False


def start_server(project_path: str | None = None, host: str = "127.0.0.1", port: int = 8080):
    """Start the web server."""
    import uvicorn

    if project_path:
        set_project_path(project_path)

    # Kill any previous instance on the same port
    _kill_previous(port)

    print(f"\n  CLU - Dashboard")
    print(f"  http://{host}:{port}")
    if project_path:
        print(f"  Project: {project_path}")
    print()

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="Unity project path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    start_server(args.project, args.host, args.port)
