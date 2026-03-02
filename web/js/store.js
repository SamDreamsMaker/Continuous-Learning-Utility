// ===== PROVIDER CONFIG STORE =====
class ProviderConfigStore {
  constructor() {
    this._state = {
      providerType: 'openai_compat',
      preset: null,
      baseUrl: '',
      apiKey: '',
      model: '',
      models: [],
      status: false,
      statusText: 'Not connected',
    };
    this._subscribers = [];
    this._restoring = false;
    this._initialized = false;  // true after first restore() from server
    this._apiKeys = {};     // per-provider key storage: { "anthropic": "sk-...", ... }
    this._connections = {};  // per-provider connection state: { "anthropic": { status, statusText, models, model }, ... }
  }

  get _providerKey() {
    const { providerType, preset } = this._state;
    return preset ? providerType + ':' + preset : providerType;
  }

  saveApiKey() {
    this._apiKeys[this._providerKey] = this._state.apiKey;
  }

  restoreApiKey() {
    const saved = this._apiKeys[this._providerKey] || '';
    this.update({ apiKey: saved });
  }

  saveConnection() {
    this._connections[this._providerKey] = {
      status: this._state.status,
      statusText: this._state.statusText,
      models: this._state.models,
      model: this._state.model,
    };
  }

  restoreConnection() {
    const saved = this._connections[this._providerKey];
    if (saved) {
      this.update({ status: saved.status, statusText: saved.statusText, models: saved.models, model: saved.model });
    } else {
      this.update({ status: false, statusText: 'Not connected', models: [], model: '' });
    }
  }

  get state() { return Object.assign({}, this._state); }

  get isCloudProvider() {
    const { providerType, preset } = this._state;
    return providerType === 'anthropic' || providerType === 'google' || preset === 'openai';
  }

  get showUrl() { return this._state.providerType === 'openai_compat' && !this._state.preset; }

  get restoring() { return this._restoring; }

  update(partial) {
    const changed = [];
    for (const key of Object.keys(partial)) {
      if (!(key in this._state)) continue;
      const oldVal = this._state[key];
      const newVal = partial[key];
      if (Array.isArray(oldVal) && Array.isArray(newVal)) {
        if (oldVal.length !== newVal.length || oldVal.some((v, i) => v !== newVal[i])) {
          this._state[key] = newVal;
          changed.push(key);
        }
      } else if (oldVal !== newVal) {
        this._state[key] = newVal;
        changed.push(key);
      }
    }
    if (changed.length) this._notify(changed);
  }

  restore(data) {
    // Only restore full state on first page load; skip on WS reconnect
    if (this._initialized) return;
    this._initialized = true;
    this._restoring = true;
    try {
      let preset = null;
      if (data.type === 'openai_compat' && data.base_url &&
          data.base_url.includes('api.openai.com')) {
        preset = 'openai';
      }
      // Force-set all values (bypass change detection)
      Object.assign(this._state, {
        providerType: data.type || 'openai_compat',
        preset,
        baseUrl: data.base_url || '',
        model: data.model || '',
        models: data.models && data.models.length ? data.models : [],
        status: data.connected ? true : false,
        statusText: data.connected ? ('Connected: ' + data.name) : 'Not connected',
      });
      // Notify ALL keys to force a full render
      this._notify(['providerType', 'preset', 'baseUrl', 'model', 'models', 'status', 'statusText']);
      // Save restored connection state for this provider
      this.saveConnection();
    } finally {
      this._restoring = false;
    }
  }

  subscribe(fn) {
    this._subscribers.push(fn);
    return () => { this._subscribers = this._subscribers.filter(s => s !== fn); };
  }

  _notify(changed) {
    const snap = this.state;
    for (const fn of this._subscribers) fn(snap, changed);
  }
}

const providerStore = new ProviderConfigStore();

// ===== CONNECTION STATE =====
// Single source of truth for send button + setup card.
// UI subscribes once; all status changes flow here automatically.
const connectionState = (() => {
  let _connected = false;
  const _subs = [];
  return {
    get connected() { return _connected; },
    set(val) {
      val = !!val;
      if (val === _connected) return;
      _connected = val;
      _subs.forEach(fn => fn(_connected));
    },
    subscribe(fn) {
      _subs.push(fn);
      fn(_connected); // fire immediately with current value
    },
  };
})();

// Sync connectionState whenever providerStore status changes
providerStore.subscribe((state) => {
  connectionState.set(state.status === true);
});
