const LS = {
  get:    (k, def) => { try { const v = localStorage.getItem(k); return v !== null ? JSON.parse(v) : (def !== undefined ? def : null); } catch { return def !== undefined ? def : null; } },
  set:    (k, v)   => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  remove: (k)      => { try { localStorage.removeItem(k); } catch {} },
};

let currentPage   = 'dashboard';
let currentAction = 'resume';
let currentJobId  = null;
let genWs         = null;
let botWs         = null;
let activePlatform = 'linkedin';
let envApiKeyConfigured = false;  // true when LLM_API_KEY env var is set on the server

const tags = { positions: [], locations: [], blCompanies: [], blTitles: [], blLocations: [] };
let genHistory = LS.get('gen_history', []);

document.addEventListener('DOMContentLoaded', function() {
  applyTheme(LS.get('theme', 'dark'));
  loadSavedApiKey();
  checkHealth();
  checkEnvConfig();
  loadStyles();
  loadPreferencesFromServer();
  loadApplications();
  refreshBotStatus();
  renderGenHistory();
  if (!LS.get('onboarding_complete', false)) openOnboarding();
  setInterval(refreshBotStatus, 10000);
  setInterval(loadDashboardStats, 30000);
  loadDashboardStats();
});

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('themeToggle').textContent = theme === 'dark' ? '\u{1F319}' : '\u2600\uFE0F';
}
function toggleTheme() {
  const t = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  LS.set('theme', t); applyTheme(t);
}

function saveApiKey() {
  const k = document.getElementById('llmApiKey').value || document.getElementById('botApiKey').value;
  if (k) LS.set('api_key', k);
}
function loadSavedApiKey() {
  const k = LS.get('api_key', ''); const p = LS.get('api_provider', 'claude'); const m = LS.get('api_model', '');
  const u = LS.get('api_url', '');
  if (k) { setVal('llmApiKey', k); setVal('botApiKey', k); setVal('oApiKey', k); }
  if (u) { setVal('llmApiUrl', u); setVal('botApiUrl', u); setVal('oApiUrl', u); }
  setVal('llmProvider', p); setVal('botProvider', p); setVal('oProvider', p);
  updateAllModelLists();
  if (m) { setVal('llmModel', m); setVal('botModel', m); setVal('oModel', m); }
}

async function checkEnvConfig() {
  try {
    const r = await fetch('/api/config');
    if (!r.ok) return;
    const d = await r.json();
    envApiKeyConfigured = !!d.llm_api_key_configured;
    if (d.llm_api_key_configured) {
      // API key is set via env var — make fields optional and show badge
      ['llmApiKey', 'botApiKey', 'oApiKey'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.value) {
          el.placeholder = 'Configured via LLM_API_KEY env var';
        }
        // Add source badge next to the field
        if (el && el.parentNode && !el.parentNode.querySelector('.config-source-badge')) {
          const badge = document.createElement('span');
          badge.className = 'config-source-badge';
          badge.textContent = 'via env var';
          badge.style.cssText = 'font-size:11px;color:#22c55e;margin-left:8px;opacity:.8;';
          el.parentNode.appendChild(badge);
        }
      });
    }
  } catch(e) { console.warn('Config check failed:', e); }
}

const PAGE_TITLES = {
  dashboard:    ['Dashboard',    'Overview of your job search'],
  resume:       ['Resume',       'Edit and save your resume YAML'],
  preferences:  ['Preferences',  'Configure job search preferences'],
  generate:     ['Generate',     'AI-powered document generation'],
  autoapply:    ['Auto Apply',   'Automated job application bot'],
  applications: ['Applications', 'History of submitted applications'],
};
function showPage(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  document.getElementById('nav-' + page).classList.add('active');
  currentPage = page;
  const [t, s] = PAGE_TITLES[page] || [page, ''];
  setEl('topbarTitle', t); setEl('topbarSub', s);
  if (page === 'applications') loadApplications();
  if (page === 'dashboard')    loadDashboardStats();
  document.getElementById('sidebar').classList.remove('open');
}
function toggleSidebar() { document.getElementById('sidebar').classList.toggle('open'); }

async function checkHealth() {
  try {
    const r = await fetch('/api/health'); const d = await r.json();
    const el = document.getElementById('healthBadge');
    if (d.status === 'ok') { el.className = 'badge badge-success'; el.textContent = '\u25CF Healthy'; }
    else { el.className = 'badge badge-warning'; el.textContent = '\u26A0 Degraded'; }
  } catch { const el = document.getElementById('healthBadge'); el.className = 'badge badge-danger'; el.textContent = '\u2715 Offline'; }
}

async function loadResumeFromServer() {
  showStatus('resumeStatus', 'Loading\u2026', 'info');
  try {
    const r = await fetch('/api/resume'); if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    setVal('resumeYaml', d.resume_yaml || '');
    showStatus('resumeStatus', 'Loaded from server.', 'success');
  } catch(e) { showStatus('resumeStatus', 'Load failed: ' + e.message, 'error'); }
}
async function saveResumeToServer() {
  showStatus('resumeStatus', 'Saving\u2026', 'info');
  try {
    const r = await fetchRetry('/api/resume', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({resume_yaml: document.getElementById('resumeYaml').value}) });
    if (!r.ok) throw new Error(await r.text());
    showStatus('resumeStatus', 'Saved successfully.', 'success');
  } catch(e) { showStatus('resumeStatus', 'Save failed: ' + e.message, 'error'); }
}
function copyResumeYaml() {
  navigator.clipboard.writeText(document.getElementById('resumeYaml').value).then(() => showStatus('resumeStatus', 'Copied to clipboard.', 'success'));
}
function loadResumeExample() {
  setVal('resumeYaml', getExampleResume());
  showStatus('resumeStatus', 'Example loaded. Save to persist.', 'info');
}
function loadResumeIntoGenerate() {
  setVal('genResumeYaml', document.getElementById('resumeYaml').value);
  showPage('generate');
}

async function uploadPdfResume(source) {
  const fileInputId = source === 'onboarding' ? 'onboardingPdfFile' : 'resumePdfFile';
  const statusId = source === 'onboarding' ? 'onboardingUploadStatus' : 'resumeUploadStatus';
  const btnId = source === 'onboarding' ? 'onboardingUploadBtn' : 'resumeUploadBtn';
  const fileInput = document.getElementById(fileInputId);
  const btn = document.getElementById(btnId);
  if (!fileInput || !fileInput.files || !fileInput.files[0]) {
    showStatus(statusId, 'Please select a PDF file first.', 'error');
    return;
  }
  const file = fileInput.files[0];
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    showStatus(statusId, 'Please select a PDF file.', 'error');
    return;
  }
  const apiKey = LS.get('api_key', '') || '';
  const provider = LS.get('api_provider', 'claude') || 'claude';
  const fd = new FormData();
  fd.append('file', file);
  fd.append('llm_api_key', apiKey);
  fd.append('llm_model_type', provider);
  fd.append('llm_model', LS.get('api_model', '') || DEFAULT_MODELS[provider] || 'claude-sonnet-4-6');
  fd.append('llm_api_url', LS.get('api_url', '') || '');
  showStatus(statusId, 'Uploading and parsing your CV... This may take a moment.', 'info');
  if (btn) btn.disabled = true;
  try {
    const r = await fetch('/api/resume/upload-pdf', { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(err.detail || 'Upload failed');
    }
    const d = await r.json();
    setVal('resumeYaml', d.resume_yaml || '');
    showStatus(statusId, 'CV parsed successfully! Review the YAML below and save when ready.', 'success');
    if (source === 'onboarding') {
      showStatus(statusId, 'CV parsed! It will be available on the Resume page. Click "Skip for Now" to continue.', 'success');
    } else {
      showStatus('resumeStatus', 'CV parsed successfully. Review and save.', 'success');
    }
    // If preferences were inferred, store them for later
    if (d.inferred_preferences) {
      LS.set('inferred_preferences', d.inferred_preferences);
    }
  } catch(e) {
    showStatus(statusId, 'Error: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadPreferencesFromServer() {
  try {
    const r = await fetch('/api/preferences'); if (!r.ok) return; const d = await r.json();
    setChk('prefRemote', d.remote ?? true); setChk('prefHybrid', d.hybrid ?? true); setChk('prefOnsite', d.onsite ?? false);
    const exp = d.experience_level || {};
    setChk('expInternship', exp.internship ?? false); setChk('expEntry', exp.entry ?? true);
    setChk('expAssociate', exp.associate ?? true); setChk('expMid', exp.mid_senior_level ?? true);
    setChk('expDirector', exp.director ?? false); setChk('expExecutive', exp.executive ?? false);
    const jt = d.job_types || {};
    setChk('jtFullTime', jt.full_time ?? true); setChk('jtContract', jt.contract ?? false);
    setChk('jtPartTime', jt.part_time ?? false); setChk('jtTemporary', jt.temporary ?? true);
    setChk('jtInternship', jt.internship ?? false); setChk('jtOther', jt.other ?? false); setChk('jtVolunteer', jt.volunteer ?? true);
    const df = d.date_filters || {};
    if (df.all_time) setRadio('dfAllTime'); else if (df.month) setRadio('dfMonth'); else if (df.week) setRadio('dfWeek'); else setRadio('df24h');
    tags.positions = d.positions || []; tags.locations = d.locations || [];
    // Apply inferred preferences from CV upload if current values are defaults
    const inferred = LS.get('inferred_preferences', null);
    if (inferred) {
      if (inferred.positions && inferred.positions.length && tags.positions.length <= 1 && (tags.positions.length === 0 || tags.positions[0] === 'Software engineer')) {
        tags.positions = inferred.positions;
      }
      if (inferred.locations && inferred.locations.length && tags.locations.length <= 1 && (tags.locations.length === 0 || tags.locations[0] === 'Germany')) {
        tags.locations = inferred.locations;
      }
      LS.remove('inferred_preferences');
    }
    tags.blCompanies = d.company_blacklist || []; tags.blTitles = d.title_blacklist || []; tags.blLocations = d.location_blacklist || [];
    renderAllTags();
    setVal('prefDistance', String(d.distance ?? 25));
    setChk('prefApplyOnce', d.apply_once_at_company ?? true);
  } catch(e) { showToast('Failed to load preferences: ' + e.message, 'warn'); }
}
async function savePreferencesToServer() {
  showStatus('prefStatus', 'Saving\u2026', 'info');
  try {
    const df = document.querySelector('input[name="dateFilter"]:checked')?.value || 'twenty_four_hours';
    const payload = {
      remote: getChk('prefRemote'), hybrid: getChk('prefHybrid'), onsite: getChk('prefOnsite'),
      experience_level: { internship: getChk('expInternship'), entry: getChk('expEntry'), associate: getChk('expAssociate'), mid_senior_level: getChk('expMid'), director: getChk('expDirector'), executive: getChk('expExecutive') },
      job_types: { full_time: getChk('jtFullTime'), contract: getChk('jtContract'), part_time: getChk('jtPartTime'), temporary: getChk('jtTemporary'), internship: getChk('jtInternship'), other: getChk('jtOther'), volunteer: getChk('jtVolunteer') },
      date_filters: { all_time: df === 'all_time', month: df === 'month', week: df === 'week', twenty_four_hours: df === 'twenty_four_hours' },
      positions: tags.positions, locations: tags.locations,
      distance: parseInt(document.getElementById('prefDistance').value || '25', 10),
      company_blacklist: tags.blCompanies, title_blacklist: tags.blTitles, location_blacklist: tags.blLocations,
      apply_once_at_company: getChk('prefApplyOnce'),
    };
    const r = await fetchRetry('/api/preferences', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (!r.ok) throw new Error(await r.text());
    showStatus('prefStatus', 'Preferences saved.', 'success');
  } catch(e) { showStatus('prefStatus', 'Save failed: ' + e.message, 'error'); showToast('Preferences save failed', 'error'); }
}

async function loadStyles() {
  try {
    const r = await fetch('/api/styles'); if (!r.ok) return;
    const d = await r.json(); const sel = document.getElementById('resumeStyle'); sel.innerHTML = '';
    (d.styles || ['classic']).forEach((s, i) => { const o = document.createElement('option'); o.value = s; o.textContent = s; if (i === 0) o.selected = true; sel.appendChild(o); });
  } catch {}
}
const MODEL_LISTS = {
  claude:      ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
  openai:      ['gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4o', 'gpt-4o-mini', 'o3', 'o4-mini'],
  gemini:      ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash'],
  ollama:      ['llama3', 'mistral', 'codellama', 'gemma', 'phi3'],
  huggingface: ['meta-llama/Llama-3-70b-chat-hf', 'mistralai/Mistral-7B-Instruct-v0.3'],
  perplexity:  ['sonar-pro', 'sonar', 'sonar-deep-research'],
};
const DEFAULT_MODELS = {
  claude: 'claude-sonnet-4-6', openai: 'gpt-4.1', gemini: 'gemini-2.5-flash',
  ollama: 'llama3', huggingface: 'meta-llama/Llama-3-70b-chat-hf', perplexity: 'sonar-pro',
};
function updateModelList(providerSelectId, modelSelectId) {
  providerSelectId = providerSelectId || 'llmProvider';
  modelSelectId = modelSelectId || 'llmModel';
  const providerEl = document.getElementById(providerSelectId);
  const sel = document.getElementById(modelSelectId);
  if (!providerEl || !sel) return;
  const p = providerEl.value;
  const savedModel = LS.get('api_model', '');
  sel.innerHTML = '';
  (MODEL_LISTS[p] || []).forEach(m => { const o = document.createElement('option'); o.value = m; o.textContent = m; sel.appendChild(o); });
  if (savedModel && [...sel.options].some(o => o.value === savedModel)) {
    sel.value = savedModel;
  }
  sel.onchange = function() { LS.set('api_model', sel.value); };
  LS.set('api_provider', p);
  // Show/hide Ollama API URL and toggle API key requirement
  toggleOllamaFields(p);
}
function toggleOllamaFields(provider) {
  document.querySelectorAll('.ollama-url-group').forEach(el => el.style.display = provider === 'ollama' ? 'block' : 'none');
}
function updateAllModelLists() {
  const p = (document.getElementById('llmProvider') || document.getElementById('oProvider') || {}).value || 'claude';
  ['oProvider','llmProvider','botProvider'].forEach(pid => { const el = document.getElementById(pid); if (el) el.value = p; });
  updateModelList('oProvider', 'oModel');
  updateModelList('llmProvider', 'llmModel');
  updateModelList('botProvider', 'botModel');
}
function selectAction(action) {
  currentAction = action;
  document.querySelectorAll('.action-card').forEach(c => c.classList.remove('selected'));
  document.getElementById('ac-' + action).classList.add('selected');
  document.getElementById('jobUrlGroup').style.display = (action !== 'resume') ? 'block' : 'none';
}
async function startGeneration() {
  const apiKey = document.getElementById('llmApiKey').value.trim();
  const provider = document.getElementById('llmProvider').value;
  if (!apiKey && !envApiKeyConfigured && provider !== 'ollama') { showStatus('genStatus', 'API key is required.', 'error'); return; }
  const yaml = document.getElementById('genResumeYaml').value.trim();
  if (!yaml)   { showStatus('genStatus', 'Resume YAML is required.', 'error'); return; }
  const btn = document.getElementById('generateBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Generating\u2026';
  setGenProgress(0, 'Starting\u2026');
  show('genProgressWrap'); hide('genDownloadWrap'); showStatus('genStatus', '', '');
  try {
    const r = await fetch('/api/generate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({
      action: currentAction, resume_yaml: yaml,
      job_url: document.getElementById('jobUrl').value.trim() || null,
      style:   document.getElementById('resumeStyle').value || null,
      llm_api_key: apiKey, llm_model_type: provider, llm_model: document.getElementById('llmModel').value,
      llm_api_url: document.getElementById('llmApiUrl').value.trim() || '',
    })});
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json(); currentJobId = d.job_id;
    connectGenWebSocket(currentJobId);
  } catch(e) {
    btn.disabled = false; btn.innerHTML = '\u26A1 Generate Document';
    showStatus('genStatus', 'Error: ' + e.message, 'error'); hide('genProgressWrap');
  }
}
function connectGenWebSocket(jobId) {
  if (genWs) { try { genWs.close(); } catch {} }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  genWs = new WebSocket(`${proto}://${location.host}/ws/${jobId}`);
  genWs.onmessage = ev => {
    try {
      const d = JSON.parse(ev.data); setGenProgress(d.progress || 0, d.message || '');
      if (d.status === 'completed') onGenComplete(jobId);
      else if (d.status === 'failed') onGenFailed(d.error || 'Unknown error');
    } catch {}
  };
  genWs.onerror = () => pollGenStatus(jobId);
}
function pollGenStatus(jobId) {
  const iv = setInterval(async () => {
    try {
      const r = await fetch(`/api/status/${jobId}`); if (!r.ok) return;
      const d = await r.json(); setGenProgress(d.progress || 0, d.message || '');
      if (d.status === 'completed') { clearInterval(iv); onGenComplete(jobId); }
      if (d.status === 'failed')    { clearInterval(iv); onGenFailed(d.error || 'Unknown'); }
    } catch {}
  }, 2000);
}
function setGenProgress(pct, label) {
  document.getElementById('genProgressBar').style.width = pct + '%';
  setEl('genProgressPct', pct + '%'); setEl('genProgressLabel', label);
}
function onGenComplete(jobId) {
  setGenProgress(100, 'Complete!');
  document.getElementById('genProgressBar').classList.add('success');
  show('genDownloadWrap');
  const btn = document.getElementById('generateBtn'); btn.disabled = false; btn.innerHTML = '\u26A1 Generate Document';
  showStatus('genStatus', 'Document generated successfully.', 'success');
  const item = { id: jobId, action: currentAction, date: new Date().toISOString() };
  genHistory.unshift(item); if (genHistory.length > 10) genHistory.pop();
  LS.set('gen_history', genHistory); renderGenHistory();
}
function onGenFailed(err) {
  document.getElementById('genProgressBar').classList.add('danger');
  const btn = document.getElementById('generateBtn'); btn.disabled = false; btn.innerHTML = '\u26A1 Generate Document';
  showStatus('genStatus', 'Generation failed: ' + err, 'error');
}
function downloadDoc() { if (currentJobId) window.open(`/api/download/${currentJobId}`, '_blank'); }
function renderGenHistory() {
  const el = document.getElementById('genHistory');
  if (!genHistory.length) { el.innerHTML = '<div style="color:var(--muted);font-size:13px">No recent generations.</div>'; return; }
  el.innerHTML = genHistory.slice(0, 5).map(h => `<div class="history-item"><div class="history-info"><h4>${h.action.replace('_', ' ')}</h4><p>${new Date(h.date).toLocaleString()}</p></div><button class="btn btn-ghost btn-sm" onclick="window.open('/api/download/${h.id}','_blank')">&#8595;</button></div>`).join('');
}

function selectPlatform(p, btn) {
  activePlatform = p;
  document.querySelectorAll('.platform-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.platform-creds').forEach(c => c.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const el = document.getElementById('creds-' + p); if (el) el.classList.add('active');
}
async function loadCredentials() {
  try {
    const r = await fetch('/api/credentials'); if (!r.ok) return; const d = await r.json();
    const pl = { linkedin: 'li', indeed: 'ind', glassdoor: 'gd', ziprecruiter: 'zr', dice: 'di' };
    Object.entries(pl).forEach(([plat, pfx]) => {
      const c = d[plat] || {};
      setVal(`${pfx}-email`, c.email || ''); setVal(`${pfx}-password`, c.password || '');
    });
    appendLog('Credentials loaded.', 'info');
  } catch(e) { appendLog('Failed to load credentials: ' + e.message, 'error'); }
}
async function saveCredentials() {
  try {
    const pl = { linkedin: 'li', indeed: 'ind', glassdoor: 'gd', ziprecruiter: 'zr', dice: 'di' };
    const payload = {};
    Object.entries(pl).forEach(([plat, pfx]) => {
      payload[plat] = { email: document.getElementById(`${pfx}-email`)?.value || '', password: document.getElementById(`${pfx}-password`)?.value || '' };
    });
    const r = await fetch('/api/credentials', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (!r.ok) throw new Error(await r.text());
    appendLog('Credentials saved.', 'success');
  } catch(e) { appendLog('Failed to save credentials: ' + e.message, 'error'); }
}
async function botStart() {
  const apiKey = document.getElementById('botApiKey').value.trim();
  const botProvider = document.getElementById('botProvider').value;
  if (!apiKey && !envApiKeyConfigured && botProvider !== 'ollama') { showAlert('botAlert', 'API key is required.', 'danger'); return; }
  try {
    const r = await fetch('/api/bot/start', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({
      platforms: [activePlatform], llm_model_type: botProvider,
      llm_model: document.getElementById('botModel').value, llm_api_key: apiKey,
      llm_api_url: document.getElementById('botApiUrl').value.trim() || '',
      min_score: parseInt(document.getElementById('botMinScore').value || '60', 10),
      max_applications: parseInt(document.getElementById('botMaxApps').value || '50', 10),
      headless: document.getElementById('botHeadless').checked,
      generate_tailored_resume: document.getElementById('botTailored').checked,
    })});
    if (!r.ok) throw new Error(await r.text());
    setBotRunning(activePlatform); connectBotWebSocket();
    appendLog('Bot started on ' + activePlatform, 'success');
  } catch(e) { showAlert('botAlert', 'Start failed: ' + e.message, 'danger'); }
}
async function botPause()  { try { await fetch('/api/bot/pause',  { method: 'POST' }); setBotPaused();  appendLog('Bot paused.',   'warn');    } catch(e) { showToast('Pause failed: ' + e.message, 'error'); } }
async function botResume() { try { await fetch('/api/bot/resume', { method: 'POST' }); setBotRunning(); appendLog('Bot resumed.',  'success'); } catch(e) { showToast('Resume failed: ' + e.message, 'error'); } }
async function botStop()   {
  try {
    await fetch('/api/bot/stop', { method: 'POST' }); setBotIdle();
    appendLog('Bot stopped.', 'warn');
    if (botWs) { try { botWs.close(); } catch {} botWs = null; }
  } catch(e) { showToast('Stop failed: ' + e.message, 'error'); }
}
function connectBotWebSocket() {
  if (botWs) { try { botWs.close(); } catch {} }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  botWs = new WebSocket(`${proto}://${location.host}/ws/bot`);
  botWs.onmessage = ev => {
    try {
      const d = JSON.parse(ev.data);
      if (d.log) appendLog(d.log, d.level || 'info');
      if (d.applied  !== undefined) { setEl('botApplied', d.applied);  setEl('dashBotApplied', d.applied); }
      if (d.skipped  !== undefined) { setEl('botSkipped', d.skipped);  setEl('dashBotSkipped', d.skipped); }
      if (d.failed   !== undefined)   setEl('botFailed',  d.failed);
      if (d.status === 'completed' || d.status === 'stopped') setBotIdle();
    } catch { appendLog(ev.data, 'info'); }
  };
  botWs.onclose = () => appendLog('WebSocket closed.', 'warn');
}
async function refreshBotStatus() {
  try {
    const r = await fetch('/api/bot/status'); if (!r.ok) return; const d = await r.json();
    const st = d.status || 'idle';
    if (st === 'running') setBotRunning(d.platform); else if (st === 'paused') setBotPaused(d.platform); else setBotIdle();
    if (d.applied !== undefined) { setEl('botApplied', d.applied); setEl('dashBotApplied', d.applied); }
    if (d.skipped !== undefined) { setEl('botSkipped', d.skipped); setEl('dashBotSkipped', d.skipped); }
    if (d.failed  !== undefined)   setEl('botFailed',  d.failed);
  } catch {}
}
function setBotRunning(platform) {
  setEl('botStatusText', 'Running' + (platform ? ' \u2014 ' + platform : '')); setEl('botStatusSub', 'Bot is actively applying to jobs');
  setClass('botStatusDot', 'bot-status-indicator running');
  hide('btnBotStart'); show('btnBotPause'); hide('btnBotResume'); show('btnBotStop');
  setEl('dashBotState', 'Running'); setClass('dashBotDot', 'bot-status-indicator running');
  if (platform) setEl('dashBotPlatform', platform);
}
function setBotPaused(platform) {
  setEl('botStatusText', 'Paused' + (platform ? ' \u2014 ' + platform : '')); setEl('botStatusSub', 'Bot is paused');
  setClass('botStatusDot', 'bot-status-indicator paused');
  hide('btnBotStart'); hide('btnBotPause'); show('btnBotResume'); show('btnBotStop');
  setEl('dashBotState', 'Paused'); setClass('dashBotDot', 'bot-status-indicator paused');
}
function setBotIdle() {
  setEl('botStatusText', 'Idle \u2014 not running'); setEl('botStatusSub', 'Start the bot to begin applying');
  setClass('botStatusDot', 'bot-status-indicator');
  show('btnBotStart'); hide('btnBotPause'); hide('btnBotResume'); hide('btnBotStop');
  setEl('dashBotState', 'Idle'); setEl('dashBotPlatform', 'No platform selected');
  setClass('dashBotDot', 'bot-status-indicator');
}
function appendLog(msg, level) {
  const el = document.getElementById('botLog');
  const cls = {info:'log-info', success:'log-success', error:'log-error', warn:'log-warn'}[level] || 'log-info';
  if (el.textContent.trim() === 'Waiting for bot to start\u2026') el.textContent = '';
  const sp = document.createElement('span'); sp.className = cls;
  sp.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`; el.appendChild(sp); el.scrollTop = el.scrollHeight;
}
function clearLog() { document.getElementById('botLog').textContent = 'Waiting for bot to start\u2026'; }

async function loadApplications() {
  const platform = document.getElementById('filterPlatform')?.value || '';
  const status   = document.getElementById('filterStatus')?.value   || '';
  const params = new URLSearchParams({ limit: 100 });
  if (platform) params.set('platform', platform); if (status) params.set('status', status);
  try {
    const r = await fetch('/api/applications?' + params); if (!r.ok) throw new Error(await r.text());
    const d = await r.json(); const apps = d.applications || []; renderApplications(apps);
    const st = d.stats || {}; const tot = st.total ?? apps.length;
    setEl('appsTotal',   tot);        setEl('appsApplied', st.applied ?? '\u2014');
    setEl('appsSkipped', st.skipped ?? '\u2014'); setEl('appsFailed',  st.failed  ?? '\u2014');
    setEl('statTotal',   tot);        setEl('statApplied', st.applied ?? '\u2014');
    setEl('statSkipped', st.skipped ?? '\u2014'); setEl('statFailed',  st.failed  ?? '\u2014');
    const badge = document.getElementById('appsBadge');
    if (apps.length > 0) { badge.textContent = apps.length; badge.classList.remove('hidden'); } else badge.classList.add('hidden');
  } catch(e) { setTableError('appsTableBody', 'Failed to load: ' + e.message, 7); }
}
function renderApplications(apps) {
  const tbody = document.getElementById('appsTableBody');
  if (!apps.length) { tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:32px">No applications found.</td></tr>'; return; }
  tbody.innerHTML = apps.map(a => {
    const badge = statusBadge(a.status || 'unknown');
    const link  = a.job_url ? `<a href="${esc(a.job_url)}" target="_blank" class="link">View &#8599;</a>` : '\u2014';
    const score = a.ai_score != null ? a.ai_score + '%' : '\u2014';
    const date  = a.date_applied ? new Date(a.date_applied).toLocaleDateString() : '\u2014';
    return `<tr><td><span class="badge badge-muted">${esc(a.platform||'\u2014')}</span></td><td>${esc(a.company||'\u2014')}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(a.job_title||'\u2014')}</td><td>${score}</td><td>${badge}</td><td>${date}</td><td>${link}</td></tr>`;
  }).join('');
}
function statusBadge(s) {
  const m = {applied:'success', skipped:'warning', failed:'danger'};
  return `<span class="badge badge-${m[s]||'muted'}">${esc(s)}</span>`;
}
function exportCsv() {
  const p = new URLSearchParams();
  const platform = document.getElementById('filterPlatform')?.value; if (platform) p.set('platform', platform);
  const status   = document.getElementById('filterStatus')?.value;   if (status)   p.set('status',   status);
  window.open('/api/applications/export/csv?' + p, '_blank');
}

async function loadDashboardStats() {
  try {
    const r = await fetch('/api/applications?limit=5'); if (!r.ok) return;
    const d = await r.json(); const st = d.stats || {}; const apps = d.applications || [];
    setEl('statTotal',   st.total   ?? '\u2014'); setEl('statApplied', st.applied ?? '\u2014');
    setEl('statSkipped', st.skipped ?? '\u2014'); setEl('statFailed',  st.failed  ?? '\u2014');
    renderRecentActivity(apps);
  } catch {}
}
function renderRecentActivity(apps) {
  const el = document.getElementById('recentActivity');
  if (!apps.length) { el.innerHTML = '<div style="color:var(--muted);font-size:13px">No recent activity.</div>'; return; }
  el.innerHTML = apps.slice(0,5).map(a => {
    const col = {applied:'var(--success)', skipped:'var(--warning)', failed:'var(--danger)'}[a.status] || 'var(--muted)';
    return `<div class="activity-item"><div class="activity-dot" style="background:${col}"></div><div><div class="activity-text">${esc(a.job_title||'Unknown')} @ ${esc(a.company||'\u2014')}</div><div class="activity-time">${esc(a.platform||'')} \u00B7 ${esc(a.status||'')} \u00B7 ${a.date_applied ? new Date(a.date_applied).toLocaleDateString() : ''}</div></div></div>`;
  }).join('');
}

const TAG_CONFIG = {
  positions:   { input: 'positionInput',   list: 'positionTags'   },
  locations:   { input: 'locationInput',   list: 'locationTags'   },
  blCompanies: { input: 'blCompanyInput',  list: 'blCompanyTags'  },
  blTitles:    { input: 'blTitleInput',    list: 'blTitleTags'    },
  blLocations: { input: 'blLocationInput', list: 'blLocationTags' },
};
function addTag(group) {
  const cfg = TAG_CONFIG[group]; const input = document.getElementById(cfg.input);
  const val = input.value.trim(); if (val && !tags[group].includes(val)) { tags[group].push(val); renderTags(group); } input.value = '';
}
function removeTag(group, idx) { tags[group].splice(idx, 1); renderTags(group); }
function tagKeydown(ev, group) { if (ev.key === 'Enter') { ev.preventDefault(); addTag(group); } }
function renderTags(group) {
  document.getElementById(TAG_CONFIG[group].list).innerHTML = tags[group].map((t,i) => `<span class="tag">${esc(t)}<button class="tag-remove" onclick="removeTag('${group}',${i})">&#215;</button></span>`).join('');
}
function renderAllTags() { Object.keys(TAG_CONFIG).forEach(g => renderTags(g)); }

let oStep = 0;
function openOnboarding() { oStep = 0; document.getElementById('onboardingOverlay').classList.remove('hidden'); renderOStep(); }
function renderOStep() {
  document.querySelectorAll('.onboarding-panel').forEach((p,i) => p.classList.toggle('active', i === oStep));
  document.querySelectorAll('.onboarding-step-dot').forEach((d,i) => { d.classList.remove('done','active'); if (i < oStep) d.classList.add('done'); else if (i === oStep) d.classList.add('active'); });
}
function oNext(step) {
  if (step === 1) {
    const k = document.getElementById('oApiKey').value.trim(); const p = document.getElementById('oProvider').value; const m = document.getElementById('oModel').value;
    const u = document.getElementById('oApiUrl').value.trim();
    if (k || p === 'ollama') {
      if (k) { LS.set('api_key', k); setVal('llmApiKey', k); setVal('botApiKey', k); }
      LS.set('api_provider', p); LS.set('api_model', m);
      if (u) { LS.set('api_url', u); setVal('llmApiUrl', u); setVal('botApiUrl', u); }
      setVal('llmProvider', p); setVal('botProvider', p);
      updateModelList('llmProvider', 'llmModel'); updateModelList('botProvider', 'botModel');
      setVal('llmModel', m); setVal('botModel', m);
    }
  }
  oStep = Math.min(oStep + 1, 3); renderOStep();
}
function oBack(step) { oStep = Math.max(oStep - 1, 0); renderOStep(); }
function oFinish() {
  LS.set('onboarding_complete', true);
  const name = document.getElementById('oName').value.trim(); if (name) LS.set('user_name', name);
  document.getElementById('onboardingOverlay').classList.add('hidden');
}
function oSkipToResume() { LS.set('onboarding_complete', true); document.getElementById('onboardingOverlay').classList.add('hidden'); showPage('resume'); }

function showStatus(id, msg, type) {
  const el = document.getElementById(id); if (!el) return;
  el.className = 'status-msg' + (msg ? ' show ' + type : ''); el.textContent = msg;
}
function showAlert(id, msg, type) {
  const el = document.getElementById(id); if (!el) return;
  el.className = 'alert show alert-' + type; el.textContent = msg;
  setTimeout(() => el.classList.remove('show'), 5000);
}
function setEl(id, val)    { const el = document.getElementById(id); if (el) el.textContent = val; }
function setVal(id, val)   { const el = document.getElementById(id); if (el) el.value = val; }
function setClass(id, cls) { const el = document.getElementById(id); if (el) el.className = cls; }
function show(id) { const el = document.getElementById(id); if (el) el.classList.remove('hidden'); }
function hide(id) { const el = document.getElementById(id); if (el) el.classList.add('hidden'); }
function getChk(id)        { return document.getElementById(id)?.checked ?? false; }
function setChk(id, val)   { const el = document.getElementById(id); if (el) el.checked = !!val; }
function setRadio(id)      { const el = document.getElementById(id); if (el) el.checked = true; }
function setTableError(tbodyId, msg, cols) {
  const el = document.getElementById(tbodyId);
  if (el) el.innerHTML = `<tr><td colspan="${cols}" style="text-align:center;color:var(--danger);padding:20px">${esc(msg)}</td></tr>`;
}
function esc(str) { return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

/* --- Toast notification system --- */
function showToast(msg, type = 'info', durationMs = 4000) {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.style.cssText = 'position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;max-width:380px;';
    document.body.appendChild(container);
  }
  const icons = { success: '\u2713', error: '\u2717', warn: '\u26A0', info: '\u2139' };
  const colors = { success: '#22c55e', error: '#ef4444', warn: '#f59e0b', info: '#3b82f6' };
  const toast = document.createElement('div');
  toast.style.cssText = `display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:8px;background:var(--card-bg,#1e1e2e);border:1px solid ${colors[type] || colors.info};color:var(--text,#e0e0e0);font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,.3);opacity:0;transition:opacity .2s;`;
  toast.innerHTML = `<span style="color:${colors[type] || colors.info};font-size:16px">${icons[type] || icons.info}</span><span>${esc(msg)}</span>`;
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, durationMs);
}

/* --- Fetch with retry for critical API calls --- */
async function fetchRetry(url, opts = {}, retries = 2) {
  for (let i = 0; i <= retries; i++) {
    try {
      const r = await fetch(url, opts);
      if (r.ok || r.status < 500) return r;
      if (i < retries) { await new Promise(ok => setTimeout(ok, 1000 * (i + 1))); continue; }
      return r;
    } catch(e) {
      if (i === retries) throw e;
      await new Promise(ok => setTimeout(ok, 1000 * (i + 1)));
    }
  }
}

function getExampleResume() {
  return `personal_information:
  name: Alex Johnson
  surname: Johnson
  date_of_birth: "1990-05-15"
  country: USA
  city: San Francisco
  address: 123 Tech Street
  phone_prefix: "+1"
  phone: "555-0100"
  email: alex.johnson@example.com
  github: https://github.com/alexjohnson
  linkedin: https://linkedin.com/in/alexjohnson

education_details:
  - degree: Bachelor of Science
    university: University of California Berkeley
    gpa: "3.8"
    graduation_year: "2012"
    field_of_study: Computer Science

experience_details:
  - position: Senior Software Engineer
    company: TechCorp Inc.
    employment_type: Full-time
    start_date: "2018-03"
    end_date: "Present"
    location: San Francisco CA
    industry: Technology
    key_responsibilities:
      - Led development of microservices architecture serving 10M+ users
      - Mentored junior engineers and conducted code reviews
    skills_acquired:
      - Python
      - Go
      - Kubernetes
      - AWS

projects:
  - name: OpenSourceProject
    description: A popular open-source library with 5k GitHub stars
    link: https://github.com/alexjohnson/opensourceproject

certifications:
  - name: AWS Solutions Architect
    description: Professional level certification

languages:
  - language: English
    proficiency: Native

availability:
  notice_period: 2 weeks

salary_expectations:
  salary_range_usd: "150000 - 200000"

self_identification:
  gender: Male
  pronouns: He/Him
  veteran: false
  disability: false
  ethnicity: White

legal_authorization:
  us_work_authorization: true
  requires_us_visa: false
  requires_us_sponsorship: false

work_preferences:
  remote_work: true
  in_person_work: false
  open_to_relocation: false
  willing_to_complete_assessments: true
  willing_to_undergo_drug_tests: false
  willing_to_undergo_background_checks: true`;
}
