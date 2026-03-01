// ===== SKILLS UI =====

function initSkills() {
  log('Skills: loading...', 'tool');
  loadSkills();
}

async function loadSkills() {
  const el = document.getElementById('skills-content');
  if (el) el.innerHTML = '<div class="empty-state">Loading...</div>';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch('/api/skills', { signal: controller.signal });
    clearTimeout(timer);
    const d = await r.json();
    renderSkills(d);
  } catch (e) {
    clearTimeout(timer);
    const msg = e.name === 'AbortError' ? 'Skills load timed out' : 'Failed to load skills';
    if (el) el.innerHTML = `<div class="empty-state">${msg}</div>`;
  }
}

function renderSkills(data) {
  const el = document.getElementById('skills-content');
  if (!el) return;

  const skills = data.skills || [];

  if (!skills.length) {
    el.innerHTML = `
      <div class="skills-header">
        <span>0 skills loaded</span>
        <button class="btn sm" onclick="reloadSkills()">Reload</button>
      </div>
      <div class="empty-state">No skills found</div>`;
    return;
  }

  const skillsHtml = skills.map(s => {
    const tierCls = s.tier === 'project' ? 'ok' : s.tier === 'user' ? 'warn' : '';
    const toolsList = s.tools.length ? escHtml(s.tools.join(', ')) : '<em>none</em>';
    const tagsList = s.tags.length ? s.tags.map(t => `<span class="skill-tag">${escHtml(t)}</span>`).join('') : '';
    const checksCount = (s.checks || []).length;
    const hasPrompt = s.has_prompt ? ' &#128196;' : '';
    const errorBadge = s.load_error ? ` <span class="badge err sm" title="${escHtml(s.load_error)}">err</span>` : '';
    return `<div class="skill-item">
      <div class="skill-row">
        <span class="skill-name">${escHtml(s.name)}</span>
        <span class="badge ${tierCls} sm">${escHtml(s.tier)}</span>
        <span class="skill-ver">v${escHtml(s.version)}</span>${hasPrompt}${errorBadge}
        <button class="btn sm" onclick="testSkill('${escHtml(s.name)}')" title="Run tests">&#9654;</button>
      </div>
      <div class="skill-desc">${escHtml(s.description || '')}</div>
      <div class="skill-meta">
        <span>Tools: ${toolsList}</span>
        ${checksCount ? `<span>Checks: ${checksCount}</span>` : ''}
      </div>
      ${tagsList ? `<div class="skill-tags">${tagsList}</div>` : ''}
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="skills-header">
      <span>${skills.length} skill${skills.length !== 1 ? 's' : ''} loaded</span>
      <button class="btn sm" onclick="reloadSkills()">Reload</button>
    </div>
    <div class="skills-list">${skillsHtml}</div>`;
}

async function reloadSkills() {
  try {
    const r = await fetch('/api/skills/reload', { method: 'POST' });
    const d = await r.json();
    const count = d.count || 0;
    log(`Skills reloaded: ${count} loaded`, count > 0 ? 'ok' : 'warn');
    loadSkills();
  } catch (e) {
    log('Skills reload failed: ' + e.message, 'err');
  }
}

async function testSkill(name) {
  log(`Running tests for skill: ${name}...`, 'tool');
  try {
    const r = await fetch(`/api/skills/${encodeURIComponent(name)}/test`, { method: 'POST' });
    const d = await r.json();
    const results = d.results || [];
    const passed = results.filter(t => t.passed).length;
    const failed = results.length - passed;
    const cls = failed > 0 ? 'err' : 'ok';
    log(`${name}: ${passed}/${results.length} tests passed${failed ? ` (${failed} failed)` : ''}`, cls);
    if (failed > 0) {
      results.filter(t => !t.passed).forEach(t => {
        log(`  FAIL ${t.test_name}: ${t.error || 'unknown'}`, 'err');
      });
    }
  } catch (e) {
    log(`Test failed for ${name}: ` + e.message, 'err');
  }
}

// Fallback: attach directly to the Skills tab button so loading works
// even if the window-name lookup in switchTab fails for any reason.
document.addEventListener('DOMContentLoaded', function () {
  var btn = document.querySelector('[data-tab="skills"]');
  if (btn) {
    btn.addEventListener('click', function () {
      if (typeof loadSkills === 'function') loadSkills();
    });
  }
});
