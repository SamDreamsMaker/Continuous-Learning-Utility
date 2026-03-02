// ===== PROVIDER CONFIG =====
providerStore.subscribe(renderProviderConfig);

function renderProviderConfig(state, changed) {
  if (changed.includes('providerType') || changed.includes('preset')) {
    const sel = document.getElementById('cfg-provider');
    for (let i = 0; i < sel.options.length; i++) {
      const opt = sel.options[i];
      if (opt.value === state.providerType && (opt.dataset.preset || null) === state.preset) {
        sel.selectedIndex = i;
        break;
      }
    }
    document.getElementById('url-group').style.display = providerStore.showUrl ? '' : 'none';
    const inputGrp = document.getElementById('model-input-group');
    const selectGrp = document.getElementById('model-select-group');
    const hasModels = state.models && state.models.length > 0;
    if (hasModels) {
      inputGrp.style.display = 'none';
      selectGrp.style.display = 'flex';
    } else {
      inputGrp.style.display = 'flex';
      selectGrp.style.display = 'none';
    }
    if (!providerStore.restoring) applyPresetDefaults(state.providerType, state.preset);
  }

  if (changed.includes('baseUrl')) {
    document.getElementById('cfg-url').value = state.baseUrl;
  }

  if (changed.includes('model')) {
    document.getElementById('cfg-model-input').value = state.model;
    const sel = document.getElementById('cfg-model-select');
    let found = false;
    for (const opt of sel.options) {
      if (opt.value === state.model) { opt.selected = true; found = true; break; }
    }
    if (!found && state.model) {
      sel.innerHTML = '<option value="' + escHtml(state.model) + '" selected>' + escHtml(state.model) + '</option>';
    }
  }

  if (changed.includes('models')) {
    const sel = document.getElementById('cfg-model-select');
    const inputGrp = document.getElementById('model-input-group');
    const selectGrp = document.getElementById('model-select-group');
    const modelGroup = document.getElementById('model-group');
    // Show model group if models available or connected
    modelGroup.style.display = (state.models.length > 0 || state.status === true) ? '' : 'none';
    if (state.models.length) {
      sel.innerHTML = state.models.map(m =>
        '<option value="' + escHtml(m) + '"' + (m === state.model ? ' selected' : '') + '>' + escHtml(m) + '</option>'
      ).join('');
      if (!sel.value && state.model) {
        sel.add(new Option(state.model, state.model, true, true), 0);
      }
      inputGrp.style.display = 'none';
      selectGrp.style.display = 'flex';
    } else {
      sel.innerHTML = '<option value="">-- Select a model --</option>';
      inputGrp.style.display = 'flex';
      selectGrp.style.display = 'none';
    }
  }

  if (changed.includes('apiKey')) {
    document.getElementById('cfg-apikey').value = state.apiKey;
  }

  if (changed.includes('status') || changed.includes('statusText')) {
    const el = document.getElementById('provider-status');
    let cls = 'err';
    if (state.status === true) cls = 'ok';
    else if (state.status === 'pending') cls = 'pending';
    el.innerHTML = '<span class="dot ' + cls + '"></span><span>' + escHtml(state.statusText) + '</span>';
    // Show model group only when connected or models loaded
    const modelGroup = document.getElementById('model-group');
    modelGroup.style.display = (state.status === true || (state.models && state.models.length > 0)) ? '' : 'none';
    // Sync chat send button and setup card with connection state
    setProviderConnected(state.status === true);
  }
}

function applyPresetDefaults(type, preset) {
  // Set URL defaults per provider type
  if (preset === 'openai') {
    providerStore.update({ baseUrl: 'https://api.openai.com/v1' });
  } else if (type === 'openai_compat') {
    providerStore.update({ baseUrl: 'http://localhost:1234/v1' });
  }
  // Restore saved connection state (status, models, model) or reset to defaults
  providerStore.restoreApiKey();
  providerStore.restoreConnection();
}

function syncFormToStore() {
  const selectVisible = document.getElementById('model-select-group').style.display !== 'none';
  providerStore.update({
    baseUrl: document.getElementById('cfg-url').value.trim(),
    apiKey: document.getElementById('cfg-apikey').value,
    model: selectVisible
      ? document.getElementById('cfg-model-select').value
      : document.getElementById('cfg-model-input').value.trim(),
  });
  providerStore.saveApiKey();
}

function onProviderTypeChange() {
  // Save current provider's state before switching
  providerStore.update({ apiKey: document.getElementById('cfg-apikey').value });
  providerStore.saveApiKey();
  providerStore.saveConnection();
  const sel = document.getElementById('cfg-provider');
  const opt = sel.options[sel.selectedIndex];
  providerStore.update({ providerType: opt.value, preset: opt.dataset.preset || null });
}

async function testProvider() {
  syncFormToStore();
  const s = providerStore.state;
  providerStore.update({ status: 'pending', statusText: 'Connecting...' });
  try {
    const r = await fetch('/api/provider/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ provider: s.providerType, base_url: s.baseUrl, api_key: s.apiKey, model: s.model }),
    });
    const d = await r.json();
    if (d.ok) {
      providerStore.update({
        status: true,
        statusText: 'Connected (' + (d.models || []).length + ' models)',
        models: d.models && d.models.length ? d.models : s.models,
      });
      providerStore.saveConnection();
      setProviderConnected(true);
    } else {
      providerStore.update({ status: false, statusText: d.error || 'Connection failed' });
      providerStore.saveConnection();
      setProviderConnected(false);
    }
  } catch (e) {
    providerStore.update({ status: false, statusText: e.message });
    providerStore.saveConnection();
    setProviderConnected(false);
  }
}

async function applyProvider() {
  syncFormToStore();
  const s = providerStore.state;
  try {
    const r = await fetch('/api/provider', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ provider: s.providerType, base_url: s.baseUrl, api_key: s.apiKey, model: s.model }),
    });
    const d = await r.json();
    if (d.ok) {
      setBadge('badge-provider', 'LLM: ' + d.model.split('/').pop(), 'ok');
      providerStore.update({ status: true, statusText: 'Applied: ' + d.name + ' / ' + d.model });
      providerStore.saveConnection();
      setProviderConnected(true);
      log('Provider change: ' + d.name + ' / ' + d.model, 'ok');
    } else {
      providerStore.update({ status: false, statusText: d.error || 'Error' });
      providerStore.saveConnection();
      setProviderConnected(false);
      log('Provider error: ' + d.error, 'err');
    }
  } catch (e) {
    providerStore.update({ status: false, statusText: e.message });
    providerStore.saveConnection();
    setProviderConnected(false);
  }
}

async function loadModels() {
  try {
    const r = await fetch('/api/provider/models');
    const d = await r.json();
    if (d.ok && d.models) {
      providerStore.update({ models: d.models });
      log(d.models.length + ' models loaded', 'ok');
    }
  } catch (e) {}
}

function toggleKeyVisibility() {
  const input = document.getElementById('cfg-apikey');
  input.type = input.type === 'password' ? 'text' : 'password';
}
