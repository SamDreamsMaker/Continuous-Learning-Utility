// ===== HEARTBEAT UI =====

let _heartbeatInterval = null;

function initHeartbeat() {
  loadHeartbeat();
  if (_heartbeatInterval) clearInterval(_heartbeatInterval);
  _heartbeatInterval = setInterval(() => {
    const el = document.getElementById('heartbeat-content');
    if (el && el.offsetParent !== null) loadHeartbeat();
  }, 10000);
}

async function loadHeartbeat() {
  try {
    const r = await fetch('/api/heartbeat/status');
    const d = await r.json();
    renderHeartbeat(d);
  } catch (e) {
    console.error('Failed to load heartbeat:', e);
  }
}

function renderHeartbeat(data) {
  const el = document.getElementById('heartbeat-content');
  if (!el) return;

  const enabled = data.enabled !== false;
  const lastTick = data.last_tick ? new Date(data.last_tick * 1000).toLocaleString() : 'Never';
  const autoTasks = data.auto_tasks_this_hour || 0;
  const maxAuto = data.max_auto_tasks_per_hour || 10;

  let checksHtml = '';
  if (data.last_results && data.last_results.length) {
    checksHtml = data.last_results.map(c => {
      const icon = c.findings?.length ? '&#9888;' : '&#10003;';
      const cls = c.findings?.length ? 'warn' : 'ok';
      const findingsCount = c.findings?.length || 0;
      return `<div class="check-item">
        <span class="check-icon ${cls}">${icon}</span>
        <span class="check-name">${escHtml(c.check || c.name || '?')}</span>
        <span class="check-count">${findingsCount} findings</span>
      </div>`;
    }).join('');
  } else {
    checksHtml = '<div class="empty-state">No checks run yet</div>';
  }

  el.innerHTML = `
    <div class="hb-status">
      <div class="hb-pulse ${enabled ? 'active' : 'inactive'}"></div>
      <span>${enabled ? 'Active' : 'Disabled'}</span>
      <button class="btn sm" onclick="triggerHeartbeat()" ${!enabled ? 'disabled' : ''}>Run Now</button>
    </div>
    <div class="hb-info">
      <div><span class="hb-label">Last tick:</span> ${lastTick}</div>
      <div><span class="hb-label">Auto tasks:</span> ${autoTasks} / ${maxAuto} this hour</div>
      <div><span class="hb-label">Interval:</span> ${data.interval || 300}s</div>
    </div>
    <h4>Checks</h4>
    <div class="checks-list">${checksHtml}</div>
  `;
}

async function triggerHeartbeat() {
  try {
    const r = await fetch('/api/heartbeat/tick', { method: 'POST' });
    const d = await r.json();
    log('Heartbeat triggered: ' + (d.tasks_created || 0) + ' tasks created', 'ok');
    loadHeartbeat();
  } catch (e) {
    log('Heartbeat trigger failed: ' + e.message, 'err');
  }
}
