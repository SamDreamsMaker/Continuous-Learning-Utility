// ===== MODULES TAB =====

async function loadModules() {
  try {
    const r = await fetch('/api/modules');
    const d = await r.json();
    renderModules(d.modules || []);
  } catch (e) {
    log('Modules error: ' + e.message, 'err');
  }
}

function renderModules(modules) {
  const el = document.getElementById('modules-content');
  if (!el) return;

  if (!modules.length) {
    el.innerHTML = '<div class="empty-state">No modules discovered</div>';
    return;
  }

  const rows = modules.map(m => {
    const typeBadge = `<span class="badge sm">${escHtml(m.type)}</span>`;
    const tierBadge = `<span class="badge sm badge-secondary">${escHtml(m.tier)}</span>`;
    const statusDot = m.running
      ? '<span class="badge-dot ok" style="display:inline-block;"></span>'
      : '<span class="badge-dot err" style="display:inline-block;"></span>';
    const actionBtn = m.running
      ? `<button class="btn sm danger" onclick="moduleAction('${escHtml(m.name)}','stop')">Stop</button>`
      : `<button class="btn sm" onclick="moduleAction('${escHtml(m.name)}','start')">Start</button>`;
    const toggleBtn = m.enabled
      ? `<button class="btn sm" onclick="moduleToggle('${escHtml(m.name)}')">Disable</button>`
      : `<button class="btn sm muted" onclick="moduleToggle('${escHtml(m.name)}')">Enable</button>`;

    return `<div class="module-item">
      <div class="module-info">
        <div class="module-header">
          ${statusDot}
          <strong>${escHtml(m.name)}</strong>
          ${typeBadge} ${tierBadge}
          <span class="module-version">v${escHtml(m.version)}</span>
        </div>
        <div class="module-desc">${escHtml(m.description || '')}</div>
      </div>
      <div class="module-actions">${toggleBtn} ${actionBtn}</div>
    </div>`;
  }).join('');

  el.innerHTML = `<div class="module-list">${rows}</div>`;
}

async function moduleAction(name, action) {
  try {
    const r = await fetch(`/api/modules/${name}/${action}`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      log(`Module ${name}: ${action}`, 'ok');
    } else {
      log(`Module ${name}: ${action} failed`, 'err');
    }
    loadModules();
  } catch (e) {
    log('Module error: ' + e.message, 'err');
  }
}

async function moduleToggle(name) {
  try {
    const r = await fetch(`/api/modules/${name}/toggle`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      log(`Module ${name}: ${d.enabled ? 'enabled' : 'disabled'}`, 'ok');
    }
    loadModules();
  } catch (e) {
    log('Module error: ' + e.message, 'err');
  }
}
