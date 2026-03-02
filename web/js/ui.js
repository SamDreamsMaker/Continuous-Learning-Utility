// ===== UI HELPERS =====
function setRunning(running) {
  isRunning = running;
  document.getElementById('running-indicator').classList.toggle('active', running);
  document.getElementById('send-btn').style.display = running ? 'none' : '';
  document.getElementById('stop-btn').style.display = running ? '' : 'none';
  document.getElementById('task-input').disabled = running;
}

function addMsg(cls, html) {
  const container = document.getElementById('messages');
  const el = document.createElement('div');
  el.className = `msg ${cls}`;
  el.innerHTML = html;
  container.appendChild(el);
  if (autoScroll) {
    container.scrollTop = container.scrollHeight;
  }
}

function scrollToBottom() {
  const c = document.getElementById('messages');
  c.scrollTop = c.scrollHeight;
  autoScroll = true;
  document.getElementById('scroll-btn').classList.remove('visible');
}

// Detect when user scrolls away from bottom
document.addEventListener('DOMContentLoaded', () => {
  const msgs = document.getElementById('messages');
  msgs.addEventListener('scroll', () => {
    const atBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 50;
    autoScroll = atBottom;
    document.getElementById('scroll-btn').classList.toggle('visible', !atBottom);
  });

  // React to connection state changes — single place that drives send button + setup card
  connectionState.subscribe(connected => {
    const sendBtn = document.getElementById('send-btn');
    const input = document.getElementById('task-input');
    if (connected) {
      document.getElementById('setup-prompt')?.remove();
      if (sendBtn) { sendBtn.disabled = false; sendBtn.classList.remove('not-connected'); sendBtn.title = ''; }
      if (input) input.placeholder = 'Describe the task for the agent... (Enter = send, Shift+Enter = new line)';
    } else {
      if (!document.getElementById('setup-prompt')) {
        const container = document.getElementById('messages');
        const card = document.createElement('div');
        card.id = 'setup-prompt';
        card.className = 'setup-prompt';
        card.innerHTML = `
          <div class="setup-prompt-icon">⚡</div>
          <div class="setup-prompt-body">
            <strong>No LLM provider connected</strong>
            <span>Configure an API key or a local model to start using the agent.</span>
          </div>
          <button class="btn primary" onclick="switchPage('config',null)">Go to Settings</button>`;
        container.appendChild(card);
      }
      if (sendBtn) { sendBtn.classList.add('not-connected'); sendBtn.title = ''; }
      if (input) input.placeholder = 'Connect an LLM provider in Settings first...';
    }
  });
});

function updateBudget(iter, maxIter, tokens, maxTokens) {
  const iterPct = Math.min(100, (iter / maxIter) * 100);
  const tokenPct = Math.min(100, (tokens / maxTokens) * 100);

  document.getElementById('iter-label').textContent = `${iter} / ${maxIter}`;
  document.getElementById('token-label').textContent = `${(tokens/1000).toFixed(1)}K / ${(maxTokens/1000).toFixed(0)}K`;

  const iterFill = document.getElementById('iter-fill');
  iterFill.style.width = iterPct + '%';
  iterFill.className = 'meter-fill' + (iterPct > 80 ? ' danger' : iterPct > 60 ? ' warn' : '');

  const tokenFill = document.getElementById('token-fill');
  tokenFill.style.width = tokenPct + '%';
  tokenFill.className = 'meter-fill' + (tokenPct > 80 ? ' danger' : tokenPct > 60 ? ' warn' : '');
}

function updateModifiedFiles(files) {
  const el = document.getElementById('modified-list');
  const strip = el && el.closest('.modified-strip');
  if (!files.length) {
    if (strip) strip.classList.remove('visible');
    if (el) el.innerHTML = '';
    return;
  }
  if (strip) strip.classList.add('visible');
  el.innerHTML = files.map(f => `<div class="modified-item">${escHtml(f)}</div>`).join('');
}

function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = `badge ${cls}` + (el.classList.contains('clickable') ? ' clickable' : '') +
    (el.classList.contains('badge-secondary') ? ' badge-secondary' : '');
}

function setWsDot(cls) {
  const el = document.getElementById('badge-ws');
  if (el) {
    el.className = `badge-dot ${cls}`;
    el.title = cls === 'ok' ? 'Server connected' : 'Server disconnected';
  }
}

// ===== PROVIDER CONNECTION STATE =====
// Thin wrapper — UI is driven reactively by connectionState subscriber below.
function setProviderConnected(connected) {
  connectionState.set(connected);
}

// ===== PAGE NAVIGATION =====
function switchPage(pageName, btn) {
  // Update nav buttons
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  // Update pages
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById('page-' + pageName);
  if (pageEl) pageEl.classList.add('active');

  // Init page data on first switch (use window[] lookup to avoid ReferenceError
  // if a page's JS file fails to load — keeps other pages functional)
  const initFnNames = {
    tasks: 'initTasks',
    heartbeat: 'initHeartbeat',
    memory: 'initMemory',
    schedules: 'initSchedules',
    alerts: 'initAlerts',
    costs: 'initCosts',
    skills: 'initSkills',
    context: 'initContext',
    modules: 'loadModules',
    config: 'initConfigPage',
  };
  const fn = window[initFnNames[pageName]];
  if (typeof fn === 'function') fn();
}

// Backward-compat alias
function switchTab(tabName, btn) { switchPage(tabName, btn); }
