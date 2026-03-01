// ===== PANEL TOGGLING =====
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('panel').classList.remove('open');
  updateOverlay();
}

function togglePanel() {
  document.getElementById('panel').classList.toggle('open');
  document.getElementById('sidebar').classList.remove('open');
  updateOverlay();
}

function closeAllPanels() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('panel').classList.remove('open');
  updateOverlay();
}

function updateOverlay() {
  const sOpen = document.getElementById('sidebar').classList.contains('open');
  const pOpen = document.getElementById('panel').classList.contains('open');
  document.getElementById('panel-overlay').classList.toggle('visible', sOpen || pOpen);
}

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
  if (!files.length) {
    el.innerHTML = '<div style="font-size:12px;color:var(--text2);">None</div>';
    return;
  }
  el.innerHTML = files.map(f => `<div class="modified-item">${escHtml(f)}</div>`).join('');
}

function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = `badge ${cls}` + (el.classList.contains('clickable') ? ' clickable' : '') +
    (el.classList.contains('badge-secondary') ? ' badge-secondary' : '');
}

// ===== TAB SWITCHING =====
function switchTab(tabName, btn) {
  // Update tab buttons
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  // Update tab content
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const tabEl = document.getElementById('tab-' + tabName);
  if (tabEl) tabEl.classList.add('active');

  // Init tab data on first switch (use window[] lookup to avoid ReferenceError
  // if a tab's JS file fails to load — keeps other tabs functional)
  const initFnNames = {
    tasks: 'initTasks',
    heartbeat: 'initHeartbeat',
    memory: 'initMemory',
    schedules: 'initSchedules',
    alerts: 'initAlerts',
    costs: 'initCosts',
    skills: 'initSkills',
  };
  const fn = window[initFnNames[tabName]];
  if (typeof fn === 'function') fn();
}
