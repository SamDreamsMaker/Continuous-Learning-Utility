// ===== MEMORY BROWSER UI =====

const MEMORY_CATEGORIES = ['conventions', 'known_issues', 'project_patterns'];

function initMemory() {
  loadMemory();
}

async function loadMemory() {
  const el = document.getElementById('memory-content');
  if (!el) return;

  try {
    const r = await fetch('/api/memory');
    const d = await r.json();
    renderMemory(d);
  } catch (e) {
    el.innerHTML = '<div class="empty-state">Failed to load memory</div>';
  }
}

function renderMemory(data) {
  const el = document.getElementById('memory-content');
  if (!el) return;

  // Today's log
  const todayLog = data.today || '';
  const todayHtml = todayLog
    ? `<div class="memory-section">
        <h4>Today's Log</h4>
        <pre class="memory-preview">${escHtml(todayLog.substring(0, 500))}</pre>
      </div>`
    : '';

  // Knowledge categories
  const catHtml = MEMORY_CATEGORIES.map(cat => {
    const content = data.knowledge?.[cat] || '';
    const isEmpty = !content;
    return `<div class="memory-section">
      <div class="memory-cat-header">
        <h4>${cat.replace(/_/g, ' ')}</h4>
        <button class="btn sm" onclick="editMemory('${cat}')">Edit</button>
      </div>
      ${isEmpty
        ? '<div class="empty-state">(empty)</div>'
        : `<pre class="memory-preview">${escHtml(content.substring(0, 300))}</pre>`
      }
    </div>`;
  }).join('');

  // Daily logs list
  const logsHtml = (data.daily_logs || []).map(l =>
    `<div class="memory-log-item">${escHtml(l)}</div>`
  ).join('') || '<div class="empty-state">No daily logs</div>';

  el.innerHTML = `
    ${todayHtml}
    ${catHtml}
    <div class="memory-section">
      <h4>Daily Logs</h4>
      ${logsHtml}
    </div>
  `;
}

async function editMemory(category) {
  // Fetch current content
  let current = '';
  try {
    const r = await fetch(`/api/memory/${category}`);
    const d = await r.json();
    current = d.content || '';
  } catch (e) {}

  // Show inline editor instead of prompt()
  const el = document.getElementById('memory-content');
  if (!el) return;
  el.innerHTML = `
    <h4>Editing: ${escHtml(category)}</h4>
    <textarea id="memory-editor" rows="12" style="width:100%;font-family:monospace;background:var(--bg2);color:var(--fg);border:1px solid var(--border);padding:8px;resize:vertical;">${escHtml(current)}</textarea>
    <div style="margin-top:8px;">
      <button class="btn sm" onclick="saveMemory('${escHtml(category)}')">Save</button>
      <button class="btn sm danger" onclick="loadMemory()">Cancel</button>
    </div>
  `;
}

async function saveMemory(category) {
  const textarea = document.getElementById('memory-editor');
  if (!textarea) return;
  const newContent = textarea.value;

  try {
    const r = await fetch(`/api/memory/${category}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: newContent }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Memory "${category}" updated`, 'ok');
      loadMemory();
    } else {
      log('Failed to update memory: ' + (d.error || ''), 'err');
    }
  } catch (e) {
    log('Memory update error: ' + e.message, 'err');
  }
}
