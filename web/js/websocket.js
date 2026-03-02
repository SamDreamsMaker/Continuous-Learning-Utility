// ===== WEBSOCKET =====
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/agent`);

  ws.onopen = () => {
    setWsDot('ok');
    hideOverlay();
    log('WebSocket connected', 'ok');
    checkStatus();
  };

  ws.onclose = () => {
    setWsDot('err');
    setRunning(false);
    log('WebSocket disconnected', 'err');
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => { setWsDot('err'); };

  ws.onmessage = (e) => {
    handleWSMessage(JSON.parse(e.data));
  };
}

function handleWSMessage(data) {
  switch (data.type) {
    case 'agent_start':
      setRunning(true);
      if (data.session_id) lastSessionId = data.session_id;
      const provInfo = data.provider ? ` (${data.provider} / ${data.model})` : '';
      addMsg('system-msg', `Agent started${provInfo}: ${escHtml(data.task)}`);
      log(`Task: ${data.task}`, 'info');
      break;

    case 'iteration':
      updateBudget(data.current, data.max, data.tokens, data.max_tokens);
      document.getElementById('running-text').textContent = `Iteration ${data.current}/${data.max}...`;
      break;

    case 'tool_call':
      if (data.name === 'think') {
        const reasoning = data.arguments.reasoning || JSON.stringify(data.arguments);
        addMsg('tool-result think-result',
          `<div class="msg-label" style="color:var(--accent2);">Agent Reasoning</div>` +
          `<div>${escHtml(reasoning)}</div>`
        );
        log(`think: ${truncate(reasoning, 80)}`, 'info');
      } else {
        const argsStr = JSON.stringify(data.arguments, null, 2);
        addMsg('tool-call',
          `<div class="msg-label">Tool Call: ${escHtml(data.name)}<button class="copy-btn" onclick="copyText(this, ${escAttr(argsStr)})">Copy</button></div>` +
          `<pre>${escHtml(argsStr)}</pre>`
        );
        log(`-> ${data.name}(${truncate(JSON.stringify(data.arguments), 80)})`, 'tool');
      }
      break;

    case 'tool_result':
      if (data.name === 'think') break;
      const resultStr = JSON.stringify(data.result, null, 2);
      const needsExpand = resultStr.length > 400;
      addMsg('tool-result',
        `<div class="msg-label">Result: ${escHtml(data.name)}<button class="copy-btn" onclick="copyText(this, ${escAttr(resultStr)})">Copy</button></div>` +
        `<div class="result-content${needsExpand ? '' : ' expanded'}""><pre>${escHtml(resultStr)}</pre></div>` +
        (needsExpand ? `<button class="expand-btn" onclick="toggleExpand(this)">Show more...</button>` : '')
      );
      if (data.result.error) {
        log(`<- ${data.name}: ERR ${data.result.error}`, 'err');
      } else {
        log(`<- ${data.name}: ok`, 'ok');
      }
      break;

    case 'agent_response':
      addMsg('assistant',
        `<div class="msg-label">Agent</div>` +
        formatMarkdown(data.content)
      );
      break;

    case 'agent_done':
      setRunning(false);
      if (data.success) {
        lastSessionId = null;
      } else if (data.session_id) {
        lastSessionId = data.session_id;
      }
      const st = data.success ? 'ok' : 'err';
      const stText = data.success ? 'Completed successfully' : `Failed: ${data.error || 'unknown'}`;
      addMsg('system-msg', `${stText} | ${data.iterations} iter | ${data.tokens} tokens`);
      if (!data.success && data.session_id) {
        addMsg('system-msg', `Session saved (${data.session_id}). Send another instruction to resume.`);
      }
      log(`Agent: ${stText}`, st);
      loadSessions();
      if (data.files_modified && data.files_modified.length > 0) {
        updateModifiedFiles(data.files_modified);
      }
      break;

    case 'warning':
      addMsg('system-msg', `Warning: ${escHtml(data.message)}`);
      log(data.message, 'warn');
      break;

    case 'error':
      addMsg('error', escHtml(data.message));
      log(data.message, 'err');
      break;

    case 'info':
      addMsg('system-msg', escHtml(data.message));
      log(data.message, 'info');
      break;
  }
}
