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
    config: 'loadSessions',
  };
  const fn = window[initFnNames[pageName]];
  if (typeof fn === 'function') fn();
}

// Backward-compat alias
function switchTab(tabName, btn) { switchPage(tabName, btn); }
