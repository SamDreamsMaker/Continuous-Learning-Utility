// ===== SESSIONS =====
async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const d = await r.json();
    const el = document.getElementById('sessions-list');
    if (!d.sessions || d.sessions.length === 0) {
      el.innerHTML = '<div style="color:var(--text2);font-size:11px;">No sessions</div>';
      return;
    }
    el.innerHTML = d.sessions.slice(0, 10).map(s => {
      const date = s.created ? new Date(s.created).toLocaleString('en-US', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) : '?';
      const task = escHtml(s.task || '').substring(0, 40);
      return `<div class="session-item">
        <div class="session-info" onclick="resumeSession('${s.id}')">
          <span class="session-id">${s.id}</span> <span class="session-date">${date}</span>
          <span class="session-task">${task}</span>
        </div>
        <button class="session-delete" onclick="deleteSession('${s.id}')" title="Delete">&#10005;</button>
      </div>`;
    }).join('');
  } catch (e) {
    log('Sessions error: ' + e.message, 'err');
  }
}

function resumeSession(sessionId) {
  if (isRunning) return;
  lastSessionId = sessionId;
  addMsg('system-msg', `Session ${sessionId} selected for resume.`);
  document.getElementById('task-input').focus();
}

async function deleteSession(sessionId) {
  try {
    await fetch(`/api/sessions/${sessionId}`, {method: 'DELETE'});
    log(`Session ${sessionId} deleted`, 'ok');
    loadSessions();
  } catch (e) {}
}

async function applyFeatures() {
  const body = {
    heartbeat_enabled: document.getElementById('feat-heartbeat').checked,
    heartbeat_auto_fix_on_error: document.getElementById('feat-autofix').checked,
    validation_enabled: document.getElementById('feat-validation').checked,
    skills_enabled: document.getElementById('feat-skills').checked,
    skills_auto_generate: document.getElementById('feat-autogen').checked,
  };
  const ctx = document.getElementById('feat-context').value;
  if (ctx) body.max_context_tokens = parseInt(ctx);
  try {
    const r = await fetch('/api/config/features', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) log('Features updated', 'ok');
    else log('Features error: ' + (d.error || 'unknown'), 'err');
  } catch (e) {
    log('Features error: ' + e.message, 'err');
  }
}

async function applyProjectConfig() {
  const body = {
    project_source_dir: document.getElementById('feat-sourcedir').value,
    project_language: document.getElementById('feat-language').value,
    project_file_extensions: document.getElementById('feat-extensions').value,
  };
  try {
    const r = await fetch('/api/config/features', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) {
      log('Project config updated', 'ok');
      checkStatus();
    } else {
      log('Project error: ' + (d.error || 'unknown'), 'err');
    }
  } catch (e) {
    log('Project error: ' + e.message, 'err');
  }
}

async function applyLlmProfile() {
  const profile = document.getElementById('cfg-llm-profile').value;
  const status = document.getElementById('llm-profile-status');
  try {
    const r = await fetch('/api/config/profile', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ profile }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`LLM profile: ${d.llm_profile}`, 'ok');
      if (status) status.textContent = `Active: ${d.llm_profile}`;
    } else {
      log('Profile error: ' + (d.error || 'unknown'), 'err');
    }
  } catch (e) {
    log('Profile error: ' + e.message, 'err');
  }
}

async function updateBudgetConfig() {
  const iterations = document.getElementById('cfg-iterations').value;
  const tokens = document.getElementById('cfg-tokens').value;
  const body = {};
  if (iterations) body.max_iterations = parseInt(iterations);
  if (tokens) body.max_total_tokens = parseInt(tokens);
  if (Object.keys(body).length === 0) return;

  try {
    const r = await fetch('/api/config/budget', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Budget: ${d.max_iterations} iter, ${(d.max_total_tokens/1000).toFixed(0)}K tokens`, 'ok');
      document.getElementById('cfg-iterations').value = '';
      document.getElementById('cfg-tokens').value = '';
    }
  } catch (e) {
    log('Budget error: ' + e.message, 'err');
  }
}
