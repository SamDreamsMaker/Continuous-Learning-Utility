// ===== AGENT CONTROL =====
let currentProject = '';

function setCurrentProject(path) {
  currentProject = path || '';
}

function sendTask() {
  const sendBtn = document.getElementById('send-btn');
  if (!connectionState.connected) {
    switchPage('config', document.querySelector('.nav-btn[onclick*="config"]'));
    return;
  }
  const input = document.getElementById('task-input');
  const task = input.value.trim();
  if (!task || isRunning || !ws || ws.readyState !== WebSocket.OPEN) return;

  addMsg('user', `<div class="msg-label">You</div>${escHtml(task)}`);
  input.value = '';
  input.style.height = 'auto';

  const payload = { action: 'run_task', task, project: currentProject || undefined };
  if (lastSessionId) {
    payload.resume_session = lastSessionId;
    log(`Resuming session ${lastSessionId}`, 'info');
    lastSessionId = null;
  }
  ws.send(JSON.stringify(payload));
}

function stopAgent() {
  if (ws) ws.close();
  setRunning(false);
  addMsg('system-msg', 'Agent stopped manually.');
  setTimeout(connectWS, 500);
}

function rollback() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({action: 'rollback'}));
}

function handleInputKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendTask();
  }
  const ta = e.target;
  setTimeout(() => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }, 0);
}
