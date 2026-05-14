/* Phone Link Bridge — app.js v4 */

// ── DOM refs ──
const statusPillEl    = document.getElementById('statusPill');
const statusPillText  = document.getElementById('statusPillText');
const connectStatusEl = document.getElementById('connectStatus');
const tokenEl         = document.getElementById('token');
const directLinkEl    = document.getElementById('directLink');
const qrImageEl       = document.getElementById('qrImage');
const copyLinkBtn     = document.getElementById('copyLink');
const saveTokenBtn    = document.getElementById('saveToken');
const refreshBtn      = document.getElementById('refresh');

const filesInputEl    = document.getElementById('filesInput');
const fileDropHintEl  = document.getElementById('fileDropHint');
const uploadBtn       = document.getElementById('uploadBtn');
const uploadStatusEl  = document.getElementById('uploadStatus');

const pasteNameEl     = document.getElementById('pasteName');
const pasteTextEl     = document.getElementById('pasteText');
const pasteSubmitBtn  = document.getElementById('pasteSubmit');
const pasteStatusEl   = document.getElementById('pasteStatus');

const messageListEl   = document.getElementById('messageList');
const msgBadgeEl      = document.getElementById('msgBadge');
const clearMsgBtn     = document.getElementById('clearMessagesBtn');

const fileListEl      = document.getElementById('fileList');
const fileCountBadge  = document.getElementById('fileCountBadge');
const sizeBarEl       = document.getElementById('sizeBar');
const sizeMetaEl      = document.getElementById('sizeMeta');
const suggestedActEl  = document.getElementById('suggestedActions');
const zipBtn          = document.getElementById('zipBtn');
const clearBtn        = document.getElementById('clearBtn');
const zipStatusEl     = document.getElementById('zipStatus');

const webhookUrlEl    = document.getElementById('webhookUrl');
const saveWebhookBtn  = document.getElementById('saveWebhook');
const webhookStatusEl = document.getElementById('webhookStatus');
const relayUrlEl      = document.getElementById('relayUrl');
const saveRelayBtn    = document.getElementById('saveRelay');

const debugLogEl      = document.getElementById('debugLog');
const toastEl         = document.getElementById('toast');

// ── Constants ──
const MAX_UPLOAD_BYTES = 5_000_000;
const SOFT_TOTAL_LIMIT = 25_000_000;
const MSG_POLL_INTERVAL = 6000;

// ── State ──
const params = new URLSearchParams(window.location.search);
const sessionId = localStorage.getItem('phoneLinkSession') || localStorage.getItem('hermesPhoneLinkSession') || makeSessionId();
localStorage.setItem('phoneLinkSession', sessionId);

let isConnected = false;
let messagePollerTimer = null;
let localMessages = [];
let unreadCount = 0;

// ── Helpers ──
function makeSessionId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  return 'session-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}

function log(msg) {
  const line = '[' + new Date().toLocaleTimeString() + '] ' + msg;
  debugLogEl.textContent = line + '\n' + debugLogEl.textContent;
}

function showToast(msg, duration = 2500) {
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  setTimeout(() => toastEl.classList.remove('show'), duration);
}

// iOS Safari over HTTP blocks navigator.clipboard and window.prompt.
// Use a hidden textarea + execCommand as fallback, then show prompt text inline.
async function copyText(text) {
  // 1. Modern clipboard API (works on HTTPS or localhost)
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // 2. Legacy execCommand (iOS Safari over HTTP)
  const el = document.createElement('textarea');
  el.value = text;
  el.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px';
  document.body.appendChild(el);
  el.focus();
  el.select();
  const ok = document.execCommand('copy');
  document.body.removeChild(el);
  if (!ok) throw new Error('execCommand copy failed');
}

function showPromptPanel(text) {
  // Show the prompt text in a selectable panel — last resort when clipboard unavailable.
  let panel = document.getElementById('promptPanel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'promptPanel';
    panel.style.cssText = [
      'position:fixed;bottom:80px;left:16px;right:16px;z-index:1000',
      'background:#1a2444;border:1px solid #5b8cff;border-radius:12px',
      'padding:12px;font-size:14px;color:#edf2ff',
    ].join(';');
    const close = document.createElement('button');
    close.textContent = '✕';
    close.style.cssText = 'float:right;background:none;border:none;color:#9fb0e0;font-size:16px;cursor:pointer;padding:0 4px';
    close.onclick = () => panel.remove();
    const label = document.createElement('div');
    label.style.cssText = 'font-size:11px;color:#9fb0e0;margin-bottom:6px;text-transform:uppercase';
    label.textContent = 'Copy this prompt:';
    const textarea = document.createElement('textarea');
    textarea.style.cssText = 'width:100%;background:#0b1020;border:1px solid #2b3768;border-radius:6px;color:#edf2ff;padding:8px;font-size:13px;resize:none;height:80px';
    textarea.readOnly = true;
    panel.appendChild(close);
    panel.appendChild(label);
    panel.appendChild(textarea);
    document.body.appendChild(panel);
  }
  panel.querySelector('textarea').value = text;
  panel.querySelector('textarea').select();
  panel.style.display = 'block';
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '0 B';
  if (bytes === 0) return '0 B';
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(Math.max(bytes, 1)) / Math.log(1024)));
  return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + sizes[i];
}

function formatTime(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString();
}

function setBusy(btn, txt) {
  btn._origText = btn.textContent;
  btn.textContent = txt;
  btn.disabled = true;
}

function clearBusy(btn) {
  if (btn._origText) btn.textContent = btn._origText;
  btn.disabled = false;
}

// ── Network ──
async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('Non-JSON: ' + text.slice(0, 200)); }
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

async function api(path, body) {
  log('POST ' + path);
  const payload = { session_id: sessionId, token: tokenEl.value, ...body };
  const data = await fetchJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return data;
}

// ── Collapsible sections ──
function initCollapsibles() {
  document.querySelectorAll('.section-header').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const body = document.getElementById(targetId);
      if (!body) return;
      const isCollapsed = body.classList.contains('collapsed');
      if (isCollapsed) {
        body.classList.remove('collapsed');
        btn.setAttribute('aria-expanded', 'true');
      } else {
        body.classList.add('collapsed');
        btn.setAttribute('aria-expanded', 'false');
      }
    });
  });
}

function collapseSection(bodyId) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  body.classList.add('collapsed');
  const btn = document.querySelector(`[data-target="${bodyId}"]`);
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function expandSection(bodyId) {
  const body = document.getElementById(bodyId);
  if (!body) return;
  body.classList.remove('collapsed');
  const btn = document.querySelector(`[data-target="${bodyId}"]`);
  if (btn) btn.setAttribute('aria-expanded', 'true');
}

// ── Tabs ──
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabId = btn.dataset.tab;
      // deactivate all tabs in same .tabs container
      btn.closest('.tabs').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      // hide all panels in same section-body
      btn.closest('.section-body').querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      const panel = document.getElementById(tabId);
      if (panel) panel.classList.remove('hidden');
    });
  });
}

// ── Status ──
function setConnected(connected, label) {
  isConnected = connected;
  if (connected) {
    statusPillEl.classList.add('connected');
    statusPillText.textContent = label || 'Connected';
  } else {
    statusPillEl.classList.remove('connected');
    statusPillText.textContent = label || 'Not connected';
  }
}

// ── Meta ──
async function loadMeta() {
  const meta = await fetchJson('/api/meta');
  const url = meta.public_url;
  directLinkEl.href = url;
  directLinkEl.textContent = url;
  qrImageEl.src = '/qr.svg?' + Date.now();
  log('Meta loaded: ' + url);
}

// ── Refresh status ──
async function refreshStatus() {
  connectStatusEl.textContent = 'Refreshing…';
  connectStatusEl.className = 'status-text busy';
  try {
    const data = await api('/api/web/status', {});
    const count = data.file_count || 0;
    setConnected(true, `Connected · ${count} file${count !== 1 ? 's' : ''}`);
    connectStatusEl.textContent = `Connected as ${data.device.name}. ${count} file(s).`;
    connectStatusEl.className = 'status-text ok';
    // Auto-collapse connect section when connected
    collapseSection('bodyConnect');
    renderFiles(data.files || []);
    renderSuggestedActions(data.files || []);
    startMessagePoller();
  } catch (err) {
    setConnected(false, 'Not connected');
    connectStatusEl.textContent = 'Not connected: ' + err.message;
    connectStatusEl.className = 'status-text bad';
    stopMessagePoller();
    expandSection('bodyConnect');
    log('Status error: ' + err.message);
    throw err;
  }
}

// ── File list rendering ──
function renderFiles(files) {
  const count = files.length;
  fileCountBadge.textContent = count;

  const total = files.reduce((s, f) => s + (f.size || 0), 0);
  const pct = Math.min(100, Math.round((total / SOFT_TOTAL_LIMIT) * 100));
  sizeBarEl.style.width = pct + '%';
  sizeBarEl.style.background = total > SOFT_TOTAL_LIMIT ? 'var(--bad)' : 'var(--primary)';
  sizeMetaEl.textContent = formatBytes(total) + ' used · soft limit ' + formatBytes(SOFT_TOTAL_LIMIT);

  fileListEl.innerHTML = '';
  if (!count) {
    fileListEl.innerHTML = '<li class="muted empty-state">No uploaded items yet.</li>';
    return;
  }

  for (const file of files) {
    const li = document.createElement('li');
    li.className = 'file-item';

    const info = document.createElement('div');
    info.className = 'file-info';

    const name = document.createElement('div');
    name.className = 'file-name';
    name.textContent = file.name || file.id;

    const meta = document.createElement('div');
    meta.className = 'file-meta';
    meta.textContent = [
      formatBytes(file.size),
      file.type || 'binary',
      formatTime(file.uploaded_at),
    ].filter(Boolean).join(' · ');

    info.appendChild(name);
    info.appendChild(meta);

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn-delete';
    delBtn.title = 'Delete file';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', () => deleteFile(file.id));

    li.appendChild(info);
    li.appendChild(delBtn);
    fileListEl.appendChild(li);
  }
}

// ── Suggested prompts ──
function getSuggestedPrompts(file) {
  if (!file) return [];
  const name = (file.name || '').toLowerCase();
  const type = (file.type || '').toLowerCase();
  const isImage = type.startsWith('image/') || /\.(png|jpg|jpeg|gif|webp)$/.test(name);
  const isPdf   = type.includes('pdf') || name.endsWith('.pdf');
  const isZip   = type.includes('zip') || name.endsWith('.zip');
  const isAudio = type.startsWith('audio/') || /\.(mp3|wav|m4a|flac)$/.test(name);
  const isText  = type.startsWith('text/') || /\.(txt|md|csv|log|json|yaml|yml)$/.test(name);
  if (isImage) return ['Describe the latest image file.', 'Extract any text from the latest image (OCR).', 'Generate a short caption for the latest image.'];
  if (isPdf)   return ['Summarize the latest PDF.', 'Extract tables from the latest PDF.', 'List the key points from the latest PDF.'];
  if (isZip)   return ['List the contents of the latest ZIP and summarize each file.', 'Extract all text files from the latest ZIP.'];
  if (isAudio) return ['Transcribe the latest audio file.', 'Summarize the latest audio file.'];
  if (isText)  return ['Summarize the latest file.', 'Extract action items / TODOs from the latest file.', 'Convert the latest file to markdown.'];
  return ['Summarize the latest file.', 'Extract key entities from the latest file.'];
}

function renderSuggestedActions(files) {
  suggestedActEl.innerHTML = '';
  if (!files || !files.length) {
    suggestedActEl.innerHTML = '<span class="muted" style="font-size:13px">Upload a file to see suggestions.</span>';
    return;
  }
  const latest = files.reduce((a, b) => (a.uploaded_at || 0) > (b.uploaded_at || 0) ? a : b);
  for (const prompt of getSuggestedPrompts(latest)) {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = prompt;
    chip.addEventListener('click', async () => {
      const relayUrl = localStorage.getItem('phoneLinkRelayUrl') || '';
      if (relayUrl) {
        const orig = chip.textContent;
        chip.textContent = '⏳ Sending…';
        chip.disabled = true;
        try {
          await fetch(relayUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, session_id: sessionId }),
          });
          showToast('Prompt sent to agent!');
          chip.textContent = '✓ Sent';
          setTimeout(() => { chip.textContent = orig; chip.disabled = false; }, 2500);
        } catch (e) {
          log('Relay failed: ' + (e.message || e) + ' — falling back to clipboard');
          chip.textContent = orig;
          chip.disabled = false;
          try { await copyText(prompt); showToast('Relay failed — copied instead'); }
          catch { showPromptPanel(prompt); }
        }
      } else {
        try {
          await copyText(prompt);
          showToast('Prompt copied!');
        } catch {
          showPromptPanel(prompt);
        }
      }
    });
    suggestedActEl.appendChild(chip);
  }
}

// ── Upload ──
async function uploadFiles() {
  const files = Array.from(filesInputEl.files || []);
  if (!files.length) {
    uploadStatusEl.textContent = 'Choose at least one file first.';
    uploadStatusEl.className = 'status-text bad';
    return;
  }
  uploadStatusEl.textContent = `Uploading ${files.length} file(s)…`;
  uploadStatusEl.className = 'status-text busy';

  const bundle = [];
  for (const file of files) {
    log('Reading ' + file.name + ' (' + file.size + ' bytes)');
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 65536) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 65536));
    }
    bundle.push({ name: file.name, mime_type: file.type || 'application/octet-stream', size: file.size, base64: btoa(binary) });
  }
  await api('/api/web/upload_bundle', { files: bundle });
  uploadStatusEl.textContent = `Uploaded ${files.length} file(s).`;
  uploadStatusEl.className = 'status-text ok';
  filesInputEl.value = '';
  fileDropHintEl.textContent = 'Choose files from Files / iCloud / On My Device';
  uploadBtn.disabled = true;
  await refreshStatus();
  if (files.length > 1) await createZip();
}

// ── Paste ──
async function savePastedText() {
  const name = (pasteNameEl.value || '').trim() || 'pasted.txt';
  const text = pasteTextEl.value || '';
  if (!text.trim()) {
    pasteStatusEl.textContent = 'Paste text first.';
    pasteStatusEl.className = 'status-text bad';
    return;
  }
  pasteStatusEl.textContent = 'Saving…';
  pasteStatusEl.className = 'status-text busy';
  await api('/api/web/paste', { name, text });
  pasteStatusEl.textContent = 'Saved ' + name + '.';
  pasteStatusEl.className = 'status-text ok';
  pasteTextEl.value = '';
  await refreshStatus();
}

// ── ZIP ──
async function createZip() {
  zipStatusEl.textContent = 'Creating zip…';
  zipStatusEl.className = 'status-text busy';
  await api('/api/web/zip', { name: 'phone-bundle.zip' });
  zipStatusEl.textContent = 'Zip created (phone-bundle.zip).';
  zipStatusEl.className = 'status-text ok';
  await refreshStatus();
}

// ── Clear ──
async function clearFiles() {
  await api('/api/web/clear', {});
  await refreshStatus();
}

// ── Delete file ──
async function deleteFile(fileId) {
  log('Deleting file ' + fileId);
  try {
    await fetchJson('/api/web/delete_file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, token: tokenEl.value, file_id: fileId }),
    });
    log('Deleted ' + fileId);
    await refreshStatus();
  } catch (err) {
    log('Delete failed: ' + err.message);
    showToast('Delete failed: ' + err.message);
  }
}

// ── Message polling ──
function startMessagePoller() {
  if (messagePollerTimer) return;
  messagePollerTimer = setInterval(pollMessages, MSG_POLL_INTERVAL);
}

function stopMessagePoller() {
  if (messagePollerTimer) {
    clearInterval(messagePollerTimer);
    messagePollerTimer = null;
  }
}

async function pollMessages() {
  if (!isConnected) return;
  try {
    const data = await api('/api/web/messages', {});
    const msgs = data.messages || [];
    if (msgs.length) {
      localMessages = localMessages.concat(msgs);
      unreadCount += msgs.length;
      renderMessages();
      expandSection('bodyMessages');
    }
  } catch {
    // silent — don't spam log for polling errors
  }
}

function renderMessages() {
  // Update badge
  if (unreadCount > 0) {
    msgBadgeEl.textContent = unreadCount;
    msgBadgeEl.style.display = '';
    msgBadgeEl.classList.add('has-new');
  } else {
    msgBadgeEl.style.display = 'none';
    msgBadgeEl.classList.remove('has-new');
  }

  messageListEl.innerHTML = '';
  if (!localMessages.length) {
    messageListEl.innerHTML = '<p class="muted empty-state">No messages yet.</p>';
    return;
  }
  // Newest first
  const sorted = [...localMessages].reverse();
  for (const msg of sorted) {
    const div = document.createElement('div');
    div.className = 'message-item';
    if (msg.title) {
      const t = document.createElement('div');
      t.className = 'message-title';
      t.textContent = msg.title;
      div.appendChild(t);
    }
    const b = document.createElement('div');
    b.className = 'message-body';
    b.textContent = msg.text;
    div.appendChild(b);
    const ts = document.createElement('div');
    ts.className = 'message-time';
    ts.textContent = formatTime(msg.sent_at);
    div.appendChild(ts);
    messageListEl.appendChild(div);
  }
}

// ── Webhook ──
async function saveWebhook() {
  const url = (webhookUrlEl.value || '').trim();
  localStorage.setItem('phoneLinkWebhook', url);
  if (!url) {
    webhookStatusEl.textContent = 'Webhook cleared.';
    webhookStatusEl.className = 'status-text muted';
    return;
  }
  try {
    await fetchJson('/api/web/set_webhook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, token: tokenEl.value, webhook_url: url }),
    });
    webhookStatusEl.textContent = 'Webhook saved.';
    webhookStatusEl.className = 'status-text ok';
    log('Webhook saved: ' + url);
  } catch (err) {
    webhookStatusEl.textContent = 'Save failed: ' + err.message;
    webhookStatusEl.className = 'status-text bad';
  }
}

// ── Share target landing ──
function handleShareLanding() {
  if (params.get('shared') === '1') {
    showToast('Shared successfully!', 3000);
    log('Share target landing detected.');
    // Clean URL
    const clean = window.location.pathname + (params.get('token') ? '?token=' + encodeURIComponent(params.get('token')) : '');
    history.replaceState({}, '', clean);
  }
}

// ── Init ──
function loadStoredValues() {
  const storedToken = params.get('token') || localStorage.getItem('phoneLinkToken') || localStorage.getItem('hermesPhoneLinkToken') || '';
  if (storedToken) {
    tokenEl.value = storedToken;
    localStorage.setItem('phoneLinkToken', storedToken);
  }
  const storedWebhook = localStorage.getItem('phoneLinkWebhook') || localStorage.getItem('hermesPhoneLinkWebhook') || '';
  if (storedWebhook) webhookUrlEl.value = storedWebhook;
  const storedRelay = localStorage.getItem('phoneLinkRelayUrl') || '';
  if (storedRelay && relayUrlEl) relayUrlEl.value = storedRelay;
}

// ── Event listeners ──
window.addEventListener('error', e => log('JS error: ' + (e.message || 'unknown')));

filesInputEl.addEventListener('change', () => {
  const count = (filesInputEl.files || []).length;
  if (count) {
    const names = Array.from(filesInputEl.files).map(f => f.name).join(', ');
    fileDropHintEl.textContent = count + ' file(s) selected: ' + names;
    uploadBtn.disabled = false;
    uploadStatusEl.textContent = count + ' file(s) ready to upload.';
    uploadStatusEl.className = 'status-text ok';
  } else {
    fileDropHintEl.textContent = 'Choose files from Files / iCloud / On My Device';
    uploadBtn.disabled = true;
    uploadStatusEl.textContent = 'No files selected.';
    uploadStatusEl.className = 'status-text muted';
  }
});

copyLinkBtn.addEventListener('click', async () => {
  const href = directLinkEl.href;
  if (!href || href === '#') return;
  try {
    await copyText(href);
    showToast('Link copied!');
  } catch {
    showPromptPanel(href);
  }
});

saveTokenBtn.addEventListener('click', async () => {
  try {
    setBusy(saveTokenBtn, 'Connecting…');
    localStorage.setItem('phoneLinkToken', tokenEl.value);
    await refreshStatus();
  } catch (err) {
    connectStatusEl.textContent = 'Connection failed: ' + err.message;
    connectStatusEl.className = 'status-text bad';
  } finally {
    clearBusy(saveTokenBtn);
  }
});

refreshBtn.addEventListener('click', async () => {
  try {
    setBusy(refreshBtn, 'Refreshing…');
    await refreshStatus();
  } catch (err) {
    connectStatusEl.textContent = 'Refresh failed: ' + err.message;
    connectStatusEl.className = 'status-text bad';
  } finally {
    clearBusy(refreshBtn);
  }
});

uploadBtn.addEventListener('click', async () => {
  try {
    setBusy(uploadBtn, 'Uploading…');
    await uploadFiles();
  } catch (err) {
    uploadStatusEl.textContent = 'Upload failed: ' + err.message;
    uploadStatusEl.className = 'status-text bad';
    log('Upload failed: ' + err.message);
  } finally {
    clearBusy(uploadBtn);
  }
});

pasteSubmitBtn.addEventListener('click', async () => {
  try {
    setBusy(pasteSubmitBtn, 'Saving…');
    await savePastedText();
  } catch (err) {
    pasteStatusEl.textContent = 'Failed: ' + err.message;
    pasteStatusEl.className = 'status-text bad';
    log('Paste failed: ' + err.message);
  } finally {
    clearBusy(pasteSubmitBtn);
  }
});

clearMsgBtn.addEventListener('click', () => {
  localMessages = [];
  unreadCount = 0;
  renderMessages();
});

zipBtn.addEventListener('click', async () => {
  try {
    setBusy(zipBtn, 'Zipping…');
    await createZip();
  } catch (err) {
    zipStatusEl.textContent = 'Zip failed: ' + err.message;
    zipStatusEl.className = 'status-text bad';
    log('Zip failed: ' + err.message);
  } finally {
    clearBusy(zipBtn);
  }
});

clearBtn.addEventListener('click', async () => {
  try {
    setBusy(clearBtn, 'Clearing…');
    await clearFiles();
  } catch (err) {
    log('Clear failed: ' + err.message);
  } finally {
    clearBusy(clearBtn);
  }
});

saveWebhookBtn.addEventListener('click', async () => {
  try {
    setBusy(saveWebhookBtn, 'Saving…');
    await saveWebhook();
  } catch (err) {
    log('Webhook save error: ' + err.message);
  } finally {
    clearBusy(saveWebhookBtn);
  }
});

if (saveRelayBtn) {
  saveRelayBtn.addEventListener('click', () => {
    const url = (relayUrlEl.value || '').trim();
    localStorage.setItem('phoneLinkRelayUrl', url);
    showToast(url ? 'Relay URL saved — chip taps will fire to your agent.' : 'Relay URL cleared.');
    log('Relay URL: ' + (url || '(cleared)'));
  });
}

// ── Boot ──
(async function init() {
  try {
    log('Session: ' + sessionId);
    initCollapsibles();
    initTabs();
    loadStoredValues();
    handleShareLanding();
    renderMessages();
    renderSuggestedActions([]);
    await loadMeta();
    if (tokenEl.value) {
      await refreshStatus();
    }
  } catch (err) {
    connectStatusEl.textContent = 'Init failed: ' + err.message;
    connectStatusEl.className = 'status-text bad';
    log('Init failed: ' + err.message);
  }
}());
