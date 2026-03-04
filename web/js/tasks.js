// ===== TASK QUEUE UI =====

const STATUS_COLORS = {
  pending: 'warn', running: 'ok', completed: 'ok',
  failed: 'err', cancelled: 'err',
};

const STATUS_ICONS = {
  pending: '&#9679;', running: '&#9654;', completed: '&#10003;',
  failed: '&#10007;', cancelled: '&#8856;',
};

let _tasksInterval = null;

function initTasks() {
  loadTasks();
  // Auto-refresh every 5s when tab is visible
  if (_tasksInterval) clearInterval(_tasksInterval);
  _tasksInterval = setInterval(() => {
    const el = document.getElementById('tasks-list');
    if (el && el.offsetParent !== null) loadTasks();
  }, 5000);
}

async function loadTasks() {
  try {
    const r = await fetch('/api/tasks?limit=30');
    const d = await r.json();
    renderTasks(d.tasks || []);
  } catch (e) {
    console.error('Failed to load tasks:', e);
  }
}

function renderTasks(tasks) {
  const el = document.getElementById('tasks-list');
  if (!el) return;

  if (!tasks.length) {
    el.innerHTML = '<div class="empty-state">No tasks in queue</div>';
    return;
  }

  el.innerHTML = tasks.map(t => {
    const statusCls = STATUS_COLORS[t.status] || '';
    const icon = STATUS_ICONS[t.status] || '';
    const taskText = (t.payload?.task || '').substring(0, 80);
    const role = t.metadata?.role ? `<span class="task-role">${escHtml(t.metadata.role)}</span>` : '';
    const time = t.created_at ? new Date(t.created_at * 1000).toLocaleTimeString() : '';
    const actions = _taskActions(t);

    return `<div class="task-item">
      <div class="task-header">
        <span class="task-status ${statusCls}" title="${t.status}">${icon}</span>
        <span class="task-id">#${t.id}</span>
        ${role}
        <span class="task-type">${t.task_type || 'manual'}</span>
        <span class="task-time">${time}</span>
      </div>
      <div class="task-text">${escHtml(taskText)}</div>
      ${t.error ? `<div class="task-error">${escHtml(t.error.substring(0, 100))}</div>` : ''}
      <div class="task-actions">${actions}</div>
    </div>`;
  }).join('');
}

function _taskActions(t) {
  const btns = [];
  if (t.status === 'pending') {
    btns.push(`<button class="btn sm danger" onclick="cancelTask(${t.id})">Cancel</button>`);
  }
  if (t.status === 'failed' || t.status === 'cancelled') {
    btns.push(`<button class="btn sm" onclick="retryTask(${t.id})">Retry</button>`);
  }
  return btns.join(' ');
}

async function cancelTask(id) {
  await fetch(`/api/tasks/${id}/cancel`, { method: 'POST' });
  loadTasks();
}

async function retryTask(id) {
  await fetch(`/api/tasks/${id}/retry`, { method: 'POST' });
  loadTasks();
}

async function enqueueNewTask() {
  const input = document.getElementById('new-task-input');
  const roleSelect = document.getElementById('new-task-role');
  if (!input || !input.value.trim()) return;

  const body = { task: input.value.trim() };
  if (roleSelect && roleSelect.value) body.role = roleSelect.value;

  try {
    const r = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (d.ok) {
      input.value = '';
      loadTasks();
      log(`Task #${d.task_id} enqueued`, 'ok');
    } else {
      log('Failed to enqueue: ' + (d.error || ''), 'err');
    }
  } catch (e) {
    log('Enqueue error: ' + e.message, 'err');
  }
}
