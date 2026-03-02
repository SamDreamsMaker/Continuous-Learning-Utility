// ===== SESSIONS =====
async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const d = await r.json();
    const list = document.getElementById('session-strip-list');
    const count = document.getElementById('session-strip-count');
    if (!list) return;
    const sessions = (d.sessions || []).slice(0, 10);
    if (count) count.textContent = sessions.length;
    if (sessions.length === 0) {
      list.innerHTML = '<div style="color:var(--text2);font-size:11px;padding:4px 0;">No sessions yet</div>';
      return;
    }
    list.innerHTML = sessions.map(s => {
      const name = escHtml(s.name || (s.task || '').slice(0, 40));
      const date = s.created ? new Date(s.created).toLocaleString('en-US', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'}) : '';
      return `<div class="session-item" id="sess-${escHtml(s.id)}">
        <div class="session-info">
          <span class="session-name" contenteditable="true"
                onblur="renameSession('${escHtml(s.id)}', this.textContent)"
                onkeydown="if(event.key==='Enter'){event.preventDefault();this.blur();}">${name}</span>
          <span class="session-date">${date}</span>
        </div>
        <div class="session-actions">
          <button class="btn sm" onclick="resumeSession('${escHtml(s.id)}')">Resume</button>
          <button class="btn sm danger" onclick="deleteSession('${escHtml(s.id)}')">&#10005;</button>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    log('Sessions error: ' + e.message, 'err');
  }
}

function toggleSessionStrip() {
  const list = document.getElementById('session-strip-list');
  if (list) list.style.display = list.style.display === 'none' ? '' : 'none';
}

function resumeSession(sessionId) {
  if (isRunning) return;
  lastSessionId = sessionId;
  switchPage('chat', document.querySelector('.nav-btn[onclick*="chat"]'));
  addMsg('system-msg', 'Session selected for resume. Type your instruction.');
  document.getElementById('task-input').focus();
  // Collapse strip after selection
  const list = document.getElementById('session-strip-list');
  if (list) list.style.display = 'none';
}

async function renameSession(sessionId, newName) {
  newName = (newName || '').trim();
  if (!newName) return;
  try {
    await fetch(`/api/sessions/${sessionId}/rename`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ name: newName }),
    });
  } catch (e) {}
}

async function deleteSession(sessionId) {
  try {
    await fetch(`/api/sessions/${sessionId}`, {method: 'DELETE'});
    log('Session deleted', 'ok');
    loadSessions();
  } catch (e) {}
}

// ===== SECRETS (Keyring) =====
const KNOWN_SECRETS = [
  { name: 'whatsapp_access_token', label: 'WhatsApp Token' },
  { name: 'whatsapp_app_secret', label: 'WhatsApp App Secret' },
  { name: 'whisper_api_key', label: 'Whisper API Key' },
  { name: 'github_token', label: 'GitHub Token' },
  { name: 'discord_webhook', label: 'Discord Webhook' },
  { name: 'slack_webhook', label: 'Slack Webhook' },
];

async function loadSecrets() {
  try {
    const r = await fetch('/api/secrets');
    const d = await r.json();
    const stored = new Set(d.secrets || []);
    const el = document.getElementById('secrets-list');
    if (!el) return;

    el.innerHTML = KNOWN_SECRETS.map(s => {
      const isStored = stored.has(s.name);
      const dot = isStored ? 'ok' : '';
      const status = isStored ? 'stored' : 'not set';
      const deleteBtn = isStored
        ? `<button class="btn sm danger" onclick="deleteSecretUI('${s.name}')">&#10005;</button>`
        : '';
      return `<div class="secret-row">
        <div class="secret-header">
          <span class="secret-label">${escHtml(s.label)}</span>
          <span class="badge-dot ${dot}" style="display:inline-block;"></span>
          <span class="secret-status">${status}</span>
        </div>
        <div style="display:flex;gap:4px;">
          <input type="password" id="secret-${s.name}" placeholder="${s.name}" style="flex:1;" />
          <button class="btn sm" onclick="saveSecretUI('${s.name}')">Save</button>
          ${deleteBtn}
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    log('Secrets error: ' + e.message, 'err');
  }
}

async function saveSecretUI(name) {
  const input = document.getElementById('secret-' + name);
  const value = input ? input.value.trim() : '';
  if (!value) { log('Enter a value first', 'warn'); return; }
  try {
    const r = await fetch(`/api/secrets/${name}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ value }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Secret '${name}' saved to keyring`, 'ok');
      if (input) input.value = '';
      loadSecrets();
    }
  } catch (e) {
    log('Secret save error: ' + e.message, 'err');
  }
}

async function deleteSecretUI(name) {
  try {
    await fetch(`/api/secrets/${name}`, { method: 'DELETE' });
    log(`Secret '${name}' removed`, 'ok');
    loadSecrets();
  } catch (e) {
    log('Secret delete error: ' + e.message, 'err');
  }
}

// ===== FEATURES =====
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

function initConfigPage() {
  loadSessions();
  loadSecrets();
}
