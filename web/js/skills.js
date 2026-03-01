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

  const headerBtns = `
    <button class="btn sm" onclick="reloadSkills()">Reload</button>
    <button class="btn sm" onclick="analyzePatterns()">Analyze Patterns</button>
    <button class="btn sm" onclick="syncRegistry()">Sync Registry</button>`;

  if (!skills.length) {
    el.innerHTML = `
      <div class="skills-header">
        <span>0 skills loaded</span>
        ${headerBtns}
      </div>
      <div class="empty-state">No skills found</div>`;
    return;
  }

  const skillsHtml = skills.map(s => {
    const tierCls = s.tier === 'project' ? 'ok' : s.tier === 'user' ? 'warn' : s.tier === 'registry' ? 'info' : '';
    const toolsList = s.tools.length ? escHtml(s.tools.join(', ')) : '<em>none</em>';
    const tagsList = s.tags.length ? s.tags.map(t => `<span class="skill-tag">${escHtml(t)}</span>`).join('') : '';
    const checksCount = (s.checks || []).length;
    const hasPrompt = s.has_prompt ? ' &#128196;' : '';
    const errorBadge = s.load_error ? ` <span class="badge err sm" title="${escHtml(s.load_error)}">err</span>` : '';
    const publishBtn = (s.tier === 'user' || s.tier === 'registry')
      ? `<button class="btn sm" onclick="publishSkill('${escHtml(s.name)}')" title="Publish to registry">&#8679;</button>`
      : '';
    return `<div class="skill-item">
      <div class="skill-row">
        <span class="skill-name">${escHtml(s.name)}</span>
        <span class="badge ${tierCls} sm">${escHtml(s.tier)}</span>
        <span class="skill-ver">v${escHtml(s.version)}</span>${hasPrompt}${errorBadge}
        <button class="btn sm" onclick="testSkill('${escHtml(s.name)}')" title="Run tests">&#9654;</button>
        ${publishBtn}
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
      ${headerBtns}
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

async function publishSkill(name) {
  log(`Publishing skill: ${name}...`, 'tool');
  try {
    const r = await fetch(`/api/skills/${encodeURIComponent(name)}/publish`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      log(`Skill published — PR: ${d.pr_url}`, 'ok');
    } else {
      log(`Publish failed: ${d.error}`, 'err');
    }
  } catch (e) {
    log('Publish error: ' + e.message, 'err');
  }
}

async function syncRegistry() {
  log('Syncing community registry...', 'tool');
  try {
    const r = await fetch('/api/skills/registry/sync', { method: 'POST' });
    const d = await r.json();
    const added = (d.added || []).length;
    const updated = (d.updated || []).length;
    const skipped = (d.skipped || []).length;
    const cls = skipped > 0 ? 'warn' : 'ok';
    log(`Registry sync: +${added} added, ~${updated} updated, ${skipped} skipped`, cls);
    if (added + updated > 0) loadSkills();
  } catch (e) {
    log('Registry sync error: ' + e.message, 'err');
  }
}

async function analyzePatterns() {
  log('Analyzing task patterns...', 'tool');
  const el = document.getElementById('skills-content');
  try {
    const r = await fetch('/api/skills/candidates');
    const d = await r.json();
    const candidates = d.candidates || [];
    const total = d.total_outcomes || 0;

    if (!candidates.length) {
      log(`Pattern analysis: ${total} outcomes, no candidates yet (need more task data)`, 'warn');
      return;
    }

    log(`Found ${candidates.length} skill candidate(s) from ${total} outcomes`, 'ok');

    // Render candidate cards below the existing skills list
    const cardsHtml = candidates.map((c, i) => `
      <div class="skill-item">
        <div class="skill-row">
          <span class="skill-name">${escHtml(c.suggested_name)}</span>
          <span class="badge warn sm">candidate</span>
          <span class="skill-ver">${c.occurrences}x / ${Math.round(c.success_rate * 100)}% ok</span>
          <button class="btn sm" onclick="generateSkill(${i})">Generate</button>
        </div>
        <div class="skill-desc">Keywords: ${escHtml(c.keyword_cluster.join(', '))}</div>
        <div class="skill-meta">
          <span>Tools: ${escHtml(c.tools_used.join(', ') || 'various')}</span>
          <span>Score: ${c.score.toFixed(1)}</span>
        </div>
      </div>`).join('');

    // Append candidates below current skills list (or replace empty state)
    const existingList = el && el.querySelector('.skills-list');
    if (existingList) {
      existingList.insertAdjacentHTML('beforeend', `
        <div style="margin-top:12px;font-size:12px;color:var(--text2);padding:4px 0">
          Skill Candidates
        </div>${cardsHtml}`);
    } else if (el) {
      el.innerHTML += `<div class="skills-list">${cardsHtml}</div>`;
    }
  } catch (e) {
    log('Pattern analysis error: ' + e.message, 'err');
  }
}

async function generateSkill(candidateIndex) {
  log(`Generating skill from candidate #${candidateIndex}...`, 'tool');
  try {
    const r = await fetch('/api/skills/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_index: candidateIndex }),
    });
    const d = await r.json();
    if (d.ok) {
      log(`Skill generated: ${d.skill_name} → ${d.install_dir}`, 'ok');
      loadSkills();
    } else {
      log(`Generation failed: ${d.error}`, 'err');
      if (d.security_errors && d.security_errors.length) {
        d.security_errors.forEach(e => log(`  Security: ${e}`, 'err'));
      }
    }
  } catch (e) {
    log('Generate error: ' + e.message, 'err');
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
