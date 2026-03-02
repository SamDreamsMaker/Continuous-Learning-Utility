// ===== API CALLS =====
async function checkStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();

    if (d.provider) {
      if (d.provider.connected) {
        const label = d.provider.model ? d.provider.model.split('/').pop() : d.provider.name;
        setBadge('badge-provider', `LLM: ${label}`, 'ok');
      } else {
        setBadge('badge-provider', 'LLM: offline', 'err');
      }
      providerStore.restore(d.provider);
      setProviderConnected(d.provider.connected);
    }

    if (d.project && d.project.path) {
      setCurrentProject(d.project.path);
    }
    if (d.config) {
      // LLM profile
      if (d.config.llm_profile) {
        const sel = document.getElementById('cfg-llm-profile');
        if (sel) sel.value = d.config.llm_profile;
        const st = document.getElementById('llm-profile-status');
        if (st) st.textContent = `Active: ${d.config.llm_profile}`;
      }
      // Feature toggles
      const setCheck = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
      setCheck('feat-heartbeat', d.config.heartbeat_enabled);
      setCheck('feat-autofix', d.config.heartbeat_auto_fix_on_error);
      setCheck('feat-validation', d.config.validation_enabled);
      setCheck('feat-skills', d.config.skills_enabled);
      setCheck('feat-autogen', d.config.skills_auto_generate);
      // Context window
      const ctxEl = document.getElementById('feat-context');
      if (ctxEl && d.config.max_context_tokens) ctxEl.placeholder = d.config.max_context_tokens;
      // Project fields
      const setVal = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined) el.value = val; };
      setVal('feat-sourcedir', d.config.project_source_dir || '');
      setVal('feat-language', d.config.project_language || '');
    }
    loadSessions();
  } catch (e) {
    log('Status check failed: ' + e.message, 'err');
  }
}

// ===== KEYBOARD SHORTCUTS =====
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeAllPanels();
  }
});

// ===== INIT =====
connectWS();
// Initialize alert badge (runs independently of tab selection)
setTimeout(updateAlertBadge, 2000);
