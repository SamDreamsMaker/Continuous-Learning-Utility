// ===== COSTS / TOKEN TRACKING UI =====

let _costsInterval = null;

function initCosts() {
  loadCosts();
  if (_costsInterval) clearInterval(_costsInterval);
  _costsInterval = setInterval(() => {
    const el = document.getElementById('costs-content');
    if (el && el.offsetParent !== null) loadCosts();
  }, 15000);
}

async function loadCosts() {
  try {
    const r = await fetch('/api/costs');
    const d = await r.json();
    renderCosts(d);
  } catch (e) {
    const el = document.getElementById('costs-content');
    if (el) el.innerHTML = '<div class="empty-state">Failed to load cost data</div>';
  }
}

function renderCosts(data) {
  const el = document.getElementById('costs-content');
  if (!el) return;

  const sessions = data.sessions || [];
  const totalTokens = data.total_tokens || 0;
  const totalPrompt = data.total_prompt_tokens || 0;
  const totalCompletion = data.total_completion_tokens || 0;

  // Recent sessions token usage
  const sessionsHtml = sessions.slice(0, 10).map(s => {
    const tokens = s.tokens || 0;
    const date = s.date ? new Date(s.date).toLocaleDateString() : '';
    const task = (s.task || '').substring(0, 50);
    return `<div class="cost-item">
      <span class="cost-task">${escHtml(task)}</span>
      <span class="cost-tokens">${formatTokens(tokens)}</span>
      <span class="cost-date">${date}</span>
    </div>`;
  }).join('') || '<div class="empty-state">No sessions yet</div>';

  el.innerHTML = `
    <div class="cost-summary">
      <div class="cost-stat">
        <div class="cost-stat-value">${formatTokens(totalTokens)}</div>
        <div class="cost-stat-label">Total tokens</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${formatTokens(totalPrompt)}</div>
        <div class="cost-stat-label">Prompt</div>
      </div>
      <div class="cost-stat">
        <div class="cost-stat-value">${formatTokens(totalCompletion)}</div>
        <div class="cost-stat-label">Completion</div>
      </div>
    </div>
    <h4>Recent Sessions</h4>
    <div class="cost-sessions">${sessionsHtml}</div>
  `;
}

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}
