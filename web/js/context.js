// ===== CONTEXT UI =====

function initContext() {
  loadContext();
}

async function loadContext() {
  const el = document.getElementById('context-content');
  if (el) el.innerHTML = '<div class="empty-state">Loading...</div>';
  try {
    const r = await fetch('/api/context');
    const d = await r.json();
    renderContext(d);
    updateContextIndicator(d.items || []);
  } catch (e) {
    if (el) el.innerHTML = '<div class="empty-state">Failed to load context</div>';
    log('Context load error: ' + e.message, 'err');
  }
}

function renderContext(data) {
  const el = document.getElementById('context-content');
  if (!el) return;

  const items = data.items || [];

  const scopeOptions = `
    <option value="always">Always (all runs)</option>
    <option value="coder">Coder only</option>
    <option value="reviewer">Reviewer only</option>
    <option value="tester">Tester only</option>`;

  const addForm = `
    <div class="context-add-form">
      <input id="ctx-name" placeholder="Name (e.g. Testing conventions)" autocomplete="off" />
      <textarea id="ctx-content" rows="4" placeholder="Instructions for the agent...&#10;&#10;Example: Always write unit tests for every new function."></textarea>
      <div style="display:flex;align-items:center;gap:8px;">
        <label style="font-size:11px;color:var(--text2);white-space:nowrap;">Scope</label>
        <select id="ctx-scope" style="flex:1;">${scopeOptions}</select>
        <button class="btn primary" onclick="submitAddContext()">Add context item</button>
      </div>
    </div>`;

  if (!items.length) {
    el.innerHTML = addForm + '<div class="empty-state">No context items — add instructions the agent should always follow.</div>';
    return;
  }

  const itemsHtml = items.map(item => {
    const disabledCls = item.enabled ? '' : ' disabled';
    const statusBadge = item.enabled
      ? '<span class="badge ok sm">active</span>'
      : '<span class="badge sm">off</span>';
    const scopeBadge = item.scope && item.scope !== 'always'
      ? `<span class="badge sm" style="background:rgba(0,212,255,0.12);color:var(--accent);">${escHtml(item.scope)}</span>`
      : '';
    const toggleLabel = item.enabled ? 'Disable' : 'Enable';
    const toggleCls = item.enabled ? 'btn sm' : 'btn sm muted';
    return `<div class="context-item${disabledCls}" id="ctx-item-${escHtml(item.id)}">
      <div class="context-item-header">
        <span class="context-item-name">${escHtml(item.name)}</span>
        ${statusBadge}
        ${scopeBadge}
        <button class="${toggleCls}" onclick="toggleContextItem('${escHtml(item.id)}', ${!item.enabled})">${toggleLabel}</button>
        <button class="btn sm danger" onclick="deleteContextItem('${escHtml(item.id)}')" title="Delete">&#10005;</button>
      </div>
      <div class="context-item-body">${escHtml(item.content)}</div>
    </div>`;
  }).join('');

  const active = items.filter(i => i.enabled).length;
  const header = `<div style="font-size:11px;color:var(--text2);margin-bottom:12px;">${items.length} item${items.length !== 1 ? 's' : ''} — ${active} active</div>`;

  el.innerHTML = addForm + header + `<div class="context-list">${itemsHtml}</div>`;
}

async function submitAddContext() {
  const name = (document.getElementById('ctx-name')?.value || '').trim();
  const content = (document.getElementById('ctx-content')?.value || '').trim();
  const scope = document.getElementById('ctx-scope')?.value || 'always';
  if (!name) {
    log('Context item name is required', 'warn');
    return;
  }
  try {
    const r = await fetch('/api/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, content, scope }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Context item added: ${name}`, 'ok');
      loadContext();
    } else {
      log('Add context failed: ' + (d.error || 'unknown'), 'err');
    }
  } catch (e) {
    log('Add context error: ' + e.message, 'err');
  }
}

async function toggleContextItem(id, enabled) {
  try {
    const r = await fetch(`/api/context/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Context item ${enabled ? 'enabled' : 'disabled'}`, enabled ? 'ok' : 'warn');
      loadContext();
    } else {
      log('Toggle context failed: ' + (d.error || 'unknown'), 'err');
    }
  } catch (e) {
    log('Toggle context error: ' + e.message, 'err');
  }
}

async function deleteContextItem(id) {
  try {
    const r = await fetch(`/api/context/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const d = await r.json();
    if (d.ok) {
      log('Context item deleted', 'warn');
      loadContext();
    } else {
      log('Delete context failed: ' + (d.error || 'unknown'), 'err');
    }
  } catch (e) {
    log('Delete context error: ' + e.message, 'err');
  }
}

function updateContextIndicator(items) {
  const active = (items || []).filter(i => i.enabled).length;

  // Nav badge
  const badge = document.getElementById('context-badge');
  if (badge) {
    if (active > 0) {
      badge.textContent = active;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  // Chat page indicator
  const indicator = document.getElementById('context-indicator');
  const indicatorText = document.getElementById('context-indicator-text');
  if (indicator) {
    if (active > 0) {
      indicator.style.display = 'flex';
      if (indicatorText) {
        indicatorText.textContent = `${active} context item${active !== 1 ? 's' : ''} active`;
      }
    } else {
      indicator.style.display = 'none';
    }
  }
}

// Load context indicator on page startup (without opening the context page)
document.addEventListener('DOMContentLoaded', async function () {
  try {
    const r = await fetch('/api/context');
    const d = await r.json();
    updateContextIndicator(d.items || []);
  } catch (_) {
    // Non-critical — indicator stays hidden
  }
});
