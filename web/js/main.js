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

    if (d.project && d.project.valid) {
      setBadge('badge-project', `${d.project.source_files || d.project.cs_files} files`, 'ok');
      setCurrentProject(d.project.path);
    } else if (d.project && d.project.path) {
      setBadge('badge-project', 'Project: invalid', 'warn');
      setCurrentProject(d.project.path);
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
