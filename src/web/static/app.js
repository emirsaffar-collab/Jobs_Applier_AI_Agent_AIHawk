        /* ========== STATE ========== */
        let currentAction = 'resume';
        let currentJobId = null;
        let ws = null;
        let downloadUrl = null;
        let genHistory = JSON.parse(localStorage.getItem('aihawk_history') || '[]');

        const tagData = {
            positions: [],
            locations: [],
            company_blacklist: [],
            title_blacklist: [],
            location_blacklist: [],
        };

        const tagInputIds = {
            positions: 'positionInput',
            locations: 'locationInput',
            company_blacklist: 'companyBlInput',
            title_blacklist: 'titleBlInput',
            location_blacklist: 'locationBlInput',
        };

        const modelOptions = {
            claude: [
                { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
                { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
                { value: 'claude-3-haiku-20240307', label: 'Claude 3 Haiku' },
            ],
            openai: [
                { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
                { value: 'gpt-4o', label: 'GPT-4o' },
                { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
            ],
            gemini: [
                { value: 'gemini-pro', label: 'Gemini Pro' },
                { value: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro' },
            ],
            ollama: [
                { value: 'llama3', label: 'Llama 3' },
                { value: 'mixtral', label: 'Mixtral' },
                { value: 'codellama', label: 'Code Llama' },
            ],
        };

        const exampleYaml = `personal_information:
  name: "John"
  surname: "Doe"
  date_of_birth: "01/15/1990"
  country: "United States"
  city: "San Francisco"
  address: "123 Tech Street"
  zip_code: "94105"
  phone_prefix: "+1"
  phone: "5551234567"
  email: "john.doe@email.com"
  github: "https://github.com/johndoe"
  linkedin: "https://www.linkedin.com/in/johndoe"

education_details:
  - education_level: "Master's Degree"
    institution: "Stanford University"
    field_of_study: "Computer Science"
    final_evaluation_grade: "3.9"
    start_date: "2018"
    year_of_completion: 2020
    additional_info:
      exam:
        "Machine Learning": "A+"
        "Distributed Systems": "A"
        "Algorithms": "A"

experience_details:
  - position: "Senior Software Engineer"
    company: "TechCorp Inc."
    employment_period: "06/2020 - Present"
    location: "San Francisco, CA"
    industry: "Technology"
    key_responsibilities:
      - responsibility: "Led backend architecture redesign reducing latency by 40%"
      - responsibility: "Mentored team of 5 junior engineers"
      - responsibility: "Implemented CI/CD pipeline with 99.9% uptime"
    skills_acquired:
      - "Python"
      - "Kubernetes"
      - "AWS"
      - "System Design"

projects:
  - name: "AI Resume Builder"
    description: "Open-source tool for generating tailored resumes using LLMs"
    link: "https://github.com/johndoe/ai-resume"

achievements:
  - name: "Employee of the Year"
    description: "Recognized for outstanding technical contributions"

certifications:
  - name: "AWS Solutions Architect"
    description: "Professional certification for cloud architecture"

languages:
  - language: "English"
    proficiency: "Native"
  - language: "Spanish"
    proficiency: "Intermediate"

interests:
  - "Machine Learning"
  - "Open Source"
  - "Cloud Architecture"`;

        /* ========== INITIALIZATION ========== */
        document.addEventListener('DOMContentLoaded', () => {
            checkHealth();
            loadStyles();
            renderHistory();
            loadResumeFromServer();
            loadPreferencesFromServer();
            setupTagEnterKeys();
        });

        /* ========== TAB SWITCHING ========== */
        function switchTab(tabName) {
            document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.getElementById('tab-' + tabName).classList.add('active');
            const tabs = document.querySelectorAll('.main-tab');
            const tabMap = ['generate', 'resume', 'settings', 'bot', 'applications'];
            const idx = tabMap.indexOf(tabName);
            if (idx >= 0 && tabs[idx]) tabs[idx].classList.add('active');
            if (tabName === 'generate') updateResumePreview();
            if (tabName === 'bot') updateBotModelOptions();
            if (tabName === 'applications') loadApplications();
        }

        /* ========== PLATFORM CREDENTIAL PANEL TOGGLE ========== */
        ['linkedin','indeed','glassdoor','ziprecruiter','dice'].forEach(p => {
            const cb = document.getElementById('plt-' + p);
            if (cb) cb.addEventListener('change', function() {
                const panel = document.getElementById('cred-' + p);
                if (panel) panel.style.display = this.checked ? 'block' : 'none';
            });
        });

        /* ========== BOT LLM MODEL OPTIONS ========== */
        function updateBotModelOptions() {
            const type = document.getElementById('bot-llm-type').value;
            const select = document.getElementById('bot-llm-model');
            const options = modelOptions[type] || [];
            select.innerHTML = options.map(o => `<option value="${o.value}">${o.label}</option>`).join('');
        }

        /* ========== CREDENTIALS ========== */
        async function loadCredentials() {
            try {
                const res = await fetch('/api/credentials');
                const data = await res.json();
                ['linkedin','indeed','glassdoor','ziprecruiter','dice'].forEach(p => {
                    const creds = data[p] || {};
                    const emailEl = document.getElementById('cred-' + p + '-email');
                    const passEl = document.getElementById('cred-' + p + '-password');
                    if (emailEl && creds.email) emailEl.value = creds.email;
                    if (passEl && creds.password) passEl.value = creds.password === '***' ? '' : creds.password;
                });
                showStatusMsg('credStatus', 'success', 'Credentials loaded.');
            } catch(e) {
                showStatusMsg('credStatus', 'error', 'Failed to load credentials: ' + e.message);
            }
        }

        async function saveCredentials() {
            const body = {};
            ['linkedin','indeed','glassdoor','ziprecruiter','dice'].forEach(p => {
                const emailEl = document.getElementById('cred-' + p + '-email');
                const passEl = document.getElementById('cred-' + p + '-password');
                if (emailEl && passEl && (emailEl.value || passEl.value)) {
                    body[p] = { email: emailEl.value, password: passEl.value };
                }
            });
            try {
                const res = await fetch('/api/credentials', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                const data = await res.json();
                if (res.ok) showStatusMsg('credStatus', 'success', 'Credentials saved.');
                else showStatusMsg('credStatus', 'error', data.detail || 'Save failed.');
            } catch(e) {
                showStatusMsg('credStatus', 'error', 'Network error: ' + e.message);
            }
        }

        /* ========== BOT CONTROL ========== */
        let botWs = null;

        function botAppendLog(msg, color) {
            const log = document.getElementById('bot-log');
            const div = document.createElement('div');
            div.style.color = color || '#d4d4d4';
            div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
            log.appendChild(div);
            log.scrollTop = log.scrollHeight;
        }

        function clearBotLog() {
            const log = document.getElementById('bot-log');
            log.innerHTML = '';
        }

        function updateBotStatus(data) {
            const stats = data.stats || {};
            document.getElementById('bot-status-text').textContent = data.status || 'idle';
            document.getElementById('bot-platform-text').textContent = stats.current_platform || '—';
            document.getElementById('bot-job-text').textContent = stats.current_job || '—';
            document.getElementById('stat-applied').textContent = stats.applied || 0;
            document.getElementById('stat-skipped').textContent = stats.skipped || 0;
            document.getElementById('stat-failed').textContent = stats.failed || 0;

            const running = data.status === 'running';
            const paused = data.status === 'paused';
            const idle = data.status === 'idle';
            document.getElementById('btn-bot-start').disabled = running || paused;
            document.getElementById('btn-bot-pause').disabled = idle || paused;
            document.getElementById('btn-bot-stop').disabled = idle;
        }

        function connectBotWs() {
            if (botWs) botWs.close();
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            botWs = new WebSocket(proto + '//' + location.host + '/ws/bot');
            botWs.onmessage = function(e) {
                const data = JSON.parse(e.data);
                if (data.msg) botAppendLog(data.msg);
                updateBotStatus(data);
            };
            botWs.onclose = function() {
                setTimeout(() => { if (document.getElementById('tab-bot').classList.contains('active')) connectBotWs(); }, 3000);
            };
        }

        async function botStart() {
            const platforms = ['linkedin','indeed','glassdoor','ziprecruiter','dice','universal']
                .filter(p => document.getElementById('plt-' + p) && document.getElementById('plt-' + p).checked);
            if (!platforms.length) { alert('Select at least one platform.'); return; }
            const apiKey = document.getElementById('bot-api-key').value.trim();
            const llmType = document.getElementById('bot-llm-type').value;
            if (!apiKey && llmType !== 'ollama') { alert('Please enter your LLM API key.'); return; }
            const maxApps = parseInt(document.getElementById('bot-max-apps').value) || 50;
            if (!confirm(`Start the bot on ${platforms.join(', ')}? It will apply to up to ${maxApps} jobs automatically.`)) return;

            const body = {
                platforms,
                llm_api_key: apiKey,
                llm_model_type: llmType,
                llm_model: document.getElementById('bot-llm-model').value,
                min_score: parseInt(document.getElementById('bot-min-score').value) || 7,
                max_applications: parseInt(document.getElementById('bot-max-apps').value) || 50,
                headless: document.getElementById('bot-headless').checked,
                generate_tailored_resume: document.getElementById('bot-tailored-resume').checked,
            };
            try {
                const res = await fetch('/api/bot/start', {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
                });
                const data = await res.json();
                if (res.ok) {
                    botAppendLog('Bot started — session ' + data.session_id, '#4ec9b0');
                    connectBotWs();
                } else {
                    botAppendLog('Start failed: ' + (data.detail || 'Unknown error'), '#f44747');
                }
            } catch(e) {
                botAppendLog('Network error: ' + e.message, '#f44747');
            }
        }

        async function botPause() {
            const s = document.getElementById('btn-bot-pause');
            if (s.textContent.includes('Pause')) {
                await fetch('/api/bot/pause', {method:'POST'});
                s.textContent = '▶ Resume';
            } else {
                await fetch('/api/bot/resume', {method:'POST'});
                s.textContent = '⏸ Pause';
            }
        }

        async function botStop() {
            await fetch('/api/bot/stop', {method:'POST'});
            botAppendLog('Stop requested...', '#ce9178');
        }

        /* ========== APPLICATIONS ========== */
        async function loadApplications() {
            const platform = document.getElementById('app-filter-platform').value;
            const status = document.getElementById('app-filter-status').value;
            let url = '/api/applications?limit=200';
            if (platform) url += '&platform=' + encodeURIComponent(platform);
            if (status) url += '&status=' + encodeURIComponent(status);
            try {
                const res = await fetch(url);
                const data = await res.json();
                // Update stats
                const stats = data.stats || {};
                document.getElementById('app-stat-total').textContent = stats.total || 0;
                document.getElementById('app-stat-applied').textContent = stats.applied || 0;
                document.getElementById('app-stat-skipped').textContent = stats.skipped || 0;
                document.getElementById('app-stat-failed').textContent = stats.failed || 0;
                // Populate table
                const tbody = document.getElementById('app-tbody');
                const apps = data.applications || [];
                if (!apps.length) {
                    tbody.innerHTML = '<tr><td colspan="7" style="padding:24px;text-align:center;color:var(--gray-400)">No applications found.</td></tr>';
                    return;
                }
                const statusColors = {applied:'var(--success)',skipped:'var(--warning)',failed:'var(--danger)',discovered:'var(--gray-500)',scored:'var(--primary)'};
                tbody.innerHTML = apps.map(a => `
                    <tr style="border-bottom:1px solid var(--gray-100);cursor:pointer" onmouseover="this.style.background='var(--gray-50)'" onmouseout="this.style.background=''">
                        <td style="padding:10px 16px"><span class="badge" style="background:var(--primary-light);color:var(--primary)">${a.platform || '—'}</span></td>
                        <td style="padding:10px 16px">${escHtml(a.company || '—')}</td>
                        <td style="padding:10px 16px">${escHtml(a.title || '—')}</td>
                        <td style="padding:10px 16px;text-align:center">${a.score ? '<strong>' + a.score + '</strong>/10' : '—'}</td>
                        <td style="padding:10px 16px"><span style="color:${statusColors[a.status]||'var(--gray-500)'};font-weight:600">${a.status || '—'}</span></td>
                        <td style="padding:10px 16px;color:var(--gray-500)">${a.applied_at ? new Date(a.applied_at).toLocaleDateString() : (a.discovered_at ? new Date(a.discovered_at).toLocaleDateString() : '—')}</td>
                        <td style="padding:10px 16px">${a.url ? '<a href="' + escHtml(a.url) + '" target="_blank" style="color:var(--primary)">Open &#8599;</a>' : '—'}</td>
                    </tr>
                `).join('');
            } catch(e) {
                console.error('Failed to load applications:', e);
            }
        }

        function escHtml(s) {
            return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        }

        function showStatusMsg(id, type, msg) {
            const el = document.getElementById(id);
            if (!el) return;
            el.className = 'status-msg status-' + type;
            el.textContent = msg;
            setTimeout(() => { el.textContent = ''; el.className = 'status-msg'; }, 5000);
        }

        function updateResumePreview() {
            const yaml = document.getElementById('resumeYaml').value.trim();
            const preview = document.getElementById('resumePreview');
            if (yaml) {
                const lines = yaml.split('\\n');
                const previewLines = lines.slice(0, 8).join('\\n');
                const more = lines.length > 8 ? '\\n... (' + (lines.length - 8) + ' more lines)' : '';
                preview.innerHTML = `<pre style="font-size:12px;color:var(--gray-600);white-space:pre-wrap;margin:0;background:var(--gray-50);padding:12px;border-radius:var(--radius);border:1px solid var(--gray-200);max-height:200px;overflow-y:auto;">${escapeHtml(previewLines + more)}</pre>`;
            } else {
                preview.innerHTML = '<p>No resume loaded yet. Go to the Resume tab to enter your data.</p>';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        /* ========== HEALTH CHECK ========== */
        async function checkHealth() {
            const badge = document.getElementById('healthBadge');
            try {
                const res = await fetch('/api/health');
                if (res.ok) {
                    const data = await res.json();
                    badge.className = 'badge badge-success';
                    badge.textContent = 'Connected';
                    if (!data.data_folder_ready && data.missing_files && data.missing_files.length > 0) {
                        const box = document.getElementById('alertBox');
                        box.className = 'alert alert-warning show';
                        box.innerHTML = '<strong>Setup required:</strong> Missing files in <code>data_folder/</code>: '
                            + data.missing_files.join(', ')
                            + '. Copy from <code>data_folder_example/</code> and fill in your details.';
                    }
                } else {
                    badge.className = 'badge badge-danger';
                    badge.textContent = 'Error';
                }
            } catch(e) {
                badge.className = 'badge badge-danger';
                badge.textContent = 'Offline';
            }
        }

        /* ========== LOAD STYLES ========== */
        async function loadStyles() {
            const select = document.getElementById('styleSelect');
            try {
                const res = await fetch('/api/styles');
                const data = await res.json();
                select.innerHTML = '';
                if (data.styles && data.styles.length > 0) {
                    data.styles.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.name;
                        opt.textContent = `${s.name} (by ${s.author})`;
                        select.appendChild(opt);
                    });
                } else {
                    select.innerHTML = '<option value="">No styles available</option>';
                }
            } catch(e) {
                select.innerHTML = '<option value="">Failed to load styles</option>';
            }
        }

        /* ========== PROVIDER CHANGE ========== */
        function onProviderChange() {
            const provider = document.getElementById('llmProvider').value;
            const modelSelect = document.getElementById('llmModel');
            const models = modelOptions[provider] || [];
            modelSelect.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.value;
                opt.textContent = m.label;
                modelSelect.appendChild(opt);
            });
        }

        /* ========== ACTION SELECTION ========== */
        function selectAction(action) {
            currentAction = action;
            document.querySelectorAll('.action-card').forEach(c => c.classList.remove('selected'));
            document.getElementById('action-' + action).classList.add('selected');
            const jobUrlGroup = document.getElementById('jobUrlGroup');
            if (action === 'resume_tailored' || action === 'cover_letter') {
                jobUrlGroup.classList.add('show');
            } else {
                jobUrlGroup.classList.remove('show');
            }
        }

        /* ========== LOAD EXAMPLE ========== */
        function loadExample() {
            document.getElementById('resumeYaml').value = exampleYaml;
            showStatusMsg('resumeStatus', 'info', 'Example template loaded (not saved to server).');
        }

        /* ========== ALERTS ========== */
        function showAlert(type, message) {
            const box = document.getElementById('alertBox');
            box.className = `alert alert-${type} show`;
            box.textContent = message;
            setTimeout(() => { box.classList.remove('show'); }, 5000);
        }

        function showStatusMsg(elementId, type, message) {
            const el = document.getElementById(elementId);
            if (!el) return;
            el.className = `status-msg ${type} show`;
            el.textContent = message;
            setTimeout(() => { el.classList.remove('show'); }, 5000);
        }

        /* ========== STATUS LOG ========== */
        function addStatusLog(message) {
            const log = document.getElementById('statusLog');
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'status-entry';
            entry.innerHTML = `<span class="status-time">${time}</span>${escapeHtml(message)}`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }

        /* ========== RESUME: LOAD / SAVE ========== */
        async function loadResumeFromServer() {
            try {
                const res = await fetch('/api/resume');
                if (!res.ok) throw new Error('Failed to load resume');
                const data = await res.json();
                if (data.resume_yaml) {
                    document.getElementById('resumeYaml').value = data.resume_yaml;
                    showStatusMsg('resumeStatus', 'success', 'Resume loaded from server.');
                }
            } catch(e) {
                showStatusMsg('resumeStatus', 'error', `Failed to load resume: ${e.message}`);
            }
        }

        async function saveResumeToServer() {
            const yaml = document.getElementById('resumeYaml').value.trim();
            if (!yaml) {
                showStatusMsg('resumeStatus', 'error', 'Resume YAML cannot be empty.');
                return;
            }
            try {
                const res = await fetch('/api/resume', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ resume_yaml: yaml }),
                });
                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Save failed');
                }
                const data = await res.json();
                showStatusMsg('resumeStatus', 'success', data.message || 'Resume saved.');
            } catch(e) {
                showStatusMsg('resumeStatus', 'error', `Failed to save: ${e.message}`);
            }
        }

        /* ========== PREFERENCES: LOAD / SAVE ========== */
        async function loadPreferencesFromServer() {
            try {
                const res = await fetch('/api/preferences');
                if (!res.ok) throw new Error('Failed to load preferences');
                const data = await res.json();
                populatePreferencesForm(data);
                showStatusMsg('settingsStatus', 'success', 'Preferences loaded from server.');
            } catch(e) {
                showStatusMsg('settingsStatus', 'error', `Failed to load preferences: ${e.message}`);
            }
        }

        function populatePreferencesForm(data) {
            document.getElementById('pref_remote').checked = !!data.remote;
            document.getElementById('pref_hybrid').checked = !!data.hybrid;
            document.getElementById('pref_onsite').checked = !!data.onsite;

            const exp = data.experience_level || {};
            document.getElementById('pref_exp_internship').checked = !!exp.internship;
            document.getElementById('pref_exp_entry').checked = !!exp.entry;
            document.getElementById('pref_exp_associate').checked = !!exp.associate;
            document.getElementById('pref_exp_mid_senior').checked = !!exp.mid_senior_level;
            document.getElementById('pref_exp_director').checked = !!exp.director;
            document.getElementById('pref_exp_executive').checked = !!exp.executive;

            const jt = data.job_types || {};
            document.getElementById('pref_jt_full_time').checked = !!jt.full_time;
            document.getElementById('pref_jt_contract').checked = !!jt.contract;
            document.getElementById('pref_jt_part_time').checked = !!jt.part_time;
            document.getElementById('pref_jt_temporary').checked = !!jt.temporary;
            document.getElementById('pref_jt_internship').checked = !!jt.internship;
            document.getElementById('pref_jt_other').checked = !!jt.other;
            document.getElementById('pref_jt_volunteer').checked = !!jt.volunteer;

            const dt = data.date || {};
            let selectedDate = '24_hours';
            if (dt.all_time) selectedDate = 'all_time';
            else if (dt.month) selectedDate = 'month';
            else if (dt.week) selectedDate = 'week';
            else if (dt['24_hours']) selectedDate = '24_hours';
            const radios = document.querySelectorAll('input[name="datePosted"]');
            radios.forEach(r => { r.checked = (r.value === selectedDate); });

            tagData.positions = Array.isArray(data.positions) ? [...data.positions] : [];
            renderTags('positions');
            tagData.locations = Array.isArray(data.locations) ? [...data.locations] : [];
            renderTags('locations');

            document.getElementById('pref_distance').value = String(data.distance != null ? data.distance : 100);

            tagData.company_blacklist = Array.isArray(data.company_blacklist) ? [...data.company_blacklist] : [];
            renderTags('company_blacklist');
            tagData.title_blacklist = Array.isArray(data.title_blacklist) ? [...data.title_blacklist] : [];
            renderTags('title_blacklist');
            tagData.location_blacklist = Array.isArray(data.location_blacklist) ? [...data.location_blacklist] : [];
            renderTags('location_blacklist');

            document.getElementById('pref_apply_once').checked = data.apply_once_at_company !== false;
        }

        function gatherPreferencesFromForm() {
            const selectedDate = document.querySelector('input[name="datePosted"]:checked');
            const dateValue = selectedDate ? selectedDate.value : '24_hours';

            return {
                remote: document.getElementById('pref_remote').checked,
                hybrid: document.getElementById('pref_hybrid').checked,
                onsite: document.getElementById('pref_onsite').checked,
                experience_level: {
                    internship: document.getElementById('pref_exp_internship').checked,
                    entry: document.getElementById('pref_exp_entry').checked,
                    associate: document.getElementById('pref_exp_associate').checked,
                    mid_senior_level: document.getElementById('pref_exp_mid_senior').checked,
                    director: document.getElementById('pref_exp_director').checked,
                    executive: document.getElementById('pref_exp_executive').checked,
                },
                job_types: {
                    full_time: document.getElementById('pref_jt_full_time').checked,
                    contract: document.getElementById('pref_jt_contract').checked,
                    part_time: document.getElementById('pref_jt_part_time').checked,
                    temporary: document.getElementById('pref_jt_temporary').checked,
                    internship: document.getElementById('pref_jt_internship').checked,
                    other: document.getElementById('pref_jt_other').checked,
                    volunteer: document.getElementById('pref_jt_volunteer').checked,
                },
                date: {
                    all_time: dateValue === 'all_time',
                    month: dateValue === 'month',
                    week: dateValue === 'week',
                    twenty_four_hours: dateValue === '24_hours',
                },
                positions: [...tagData.positions],
                locations: [...tagData.locations],
                apply_once_at_company: document.getElementById('pref_apply_once').checked,
                distance: parseInt(document.getElementById('pref_distance').value, 10),
                company_blacklist: [...tagData.company_blacklist],
                title_blacklist: [...tagData.title_blacklist],
                location_blacklist: [...tagData.location_blacklist],
            };
        }

        async function savePreferencesToServer() {
            const prefs = gatherPreferencesFromForm();
            try {
                const res = await fetch('/api/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(prefs),
                });
                if (!res.ok) {
                    const err = await res.json();
                    const detail = err.detail;
                    const msg = Array.isArray(detail) ? detail.join('; ') : (detail || 'Save failed');
                    throw new Error(msg);
                }
                const data = await res.json();
                showStatusMsg('settingsStatus', 'success', data.message || 'Preferences saved.');
            } catch(e) {
                showStatusMsg('settingsStatus', 'error', `Failed to save: ${e.message}`);
            }
        }

        /* ========== TAG MANAGEMENT ========== */
        function setupTagEnterKeys() {
            Object.entries(tagInputIds).forEach(([key, inputId]) => {
                const el = document.getElementById(inputId);
                if (el) {
                    el.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            addTag(key);
                        }
                    });
                }
            });
        }

        function addTag(group) {
            const inputId = tagInputIds[group];
            const input = document.getElementById(inputId);
            if (!input) return;
            const val = input.value.trim();
            if (!val) return;
            if (tagData[group].includes(val)) {
                input.value = '';
                return;
            }
            tagData[group].push(val);
            input.value = '';
            renderTags(group);
        }

        function removeTag(group, index) {
            tagData[group].splice(index, 1);
            renderTags(group);
        }

        function renderTags(group) {
            const container = document.getElementById(group + '-tags');
            if (!container) return;
            if (tagData[group].length === 0) {
                container.innerHTML = '<span style="color:var(--gray-400);font-size:12px;">None</span>';
                return;
            }
            container.innerHTML = tagData[group].map((item, i) =>
                `<span class="tag">${escapeHtml(item)}<button class="tag-remove" onclick="removeTag('${group}', ${i})" title="Remove">&times;</button></span>`
            ).join('');
        }

        /* ========== GENERATION ========== */
        async function startGeneration() {
            const apiKey = document.getElementById('apiKey').value.trim();
            const resumeYaml = document.getElementById('resumeYaml').value.trim();
            const jobUrl = document.getElementById('jobUrl').value.trim();
            const style = document.getElementById('styleSelect').value;
            const provider = document.getElementById('llmProvider').value;
            const model = document.getElementById('llmModel').value;

            if (!apiKey) { showAlert('error', 'Please enter your API key.'); return; }
            if (!resumeYaml) {
                showAlert('error', 'No resume data found. Please go to the Resume tab and enter your resume YAML.');
                return;
            }
            if ((currentAction === 'resume_tailored' || currentAction === 'cover_letter') && !jobUrl) {
                showAlert('error', 'Please enter a job posting URL for tailored documents.');
                return;
            }

            const btn = document.getElementById('generateBtn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Generating...';
            document.getElementById('downloadSection').classList.add('hidden');
            document.getElementById('progressContainer').classList.add('active');
            document.getElementById('progressBar').style.width = '0%';
            document.getElementById('progressBar').className = 'progress-bar-fill';
            document.getElementById('progressPercent').textContent = '0%';
            document.getElementById('progressText').textContent = 'Starting...';
            document.getElementById('statusLog').innerHTML = '';
            addStatusLog('Submitting generation request...');

            try {
                const res = await fetch('/api/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: currentAction,
                        resume_yaml: resumeYaml,
                        job_url: jobUrl || null,
                        style: style || null,
                        llm_api_key: apiKey,
                        llm_model_type: provider,
                        llm_model: model,
                    }),
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || 'Request failed');
                }

                const data = await res.json();
                currentJobId = data.job_id;
                addStatusLog(`Job created: ${currentJobId.substring(0, 8)}...`);
                connectWebSocket(currentJobId);
                pollStatus(currentJobId);

            } catch(err) {
                showAlert('error', `Failed to start generation: ${err.message}`);
                btn.disabled = false;
                btn.innerHTML = '&#9889; Generate Document';
                document.getElementById('progressContainer').classList.remove('active');
            }
        }

        /* ========== WEBSOCKET ========== */
        function connectWebSocket(jobId) {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/${jobId}`;
            try {
                ws = new WebSocket(wsUrl);
                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    updateProgress(data);
                };
                ws.onerror = () => { /* Fallback to polling */ };
                ws.onclose = () => { ws = null; };
            } catch(e) { /* Fallback to polling */ }
        }

        /* ========== POLLING ========== */
        async function pollStatus(jobId) {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/status/${jobId}`);
                    const data = await res.json();
                    updateProgress(data);
                    if (data.status === 'completed' || data.status === 'failed') {
                        clearInterval(interval);
                    }
                } catch(e) { /* continue polling */ }
            }, 2000);
        }

        /* ========== PROGRESS UI ========== */
        function updateProgress(data) {
            const bar = document.getElementById('progressBar');
            const percent = document.getElementById('progressPercent');
            const text = document.getElementById('progressText');
            const btn = document.getElementById('generateBtn');

            bar.style.width = `${data.progress || 0}%`;
            percent.textContent = `${data.progress || 0}%`;
            text.textContent = data.message || '';
            addStatusLog(data.message || data.status);

            if (data.status === 'completed') {
                bar.classList.add('success');
                btn.disabled = false;
                btn.innerHTML = '&#9889; Generate Document';
                downloadUrl = data.download_url;
                document.getElementById('downloadSection').classList.remove('hidden');
                showAlert('success', 'Document generated successfully! Click Download to save.');
                addToHistory(currentAction, downloadUrl);
                if (ws) { ws.close(); ws = null; }
            } else if (data.status === 'failed') {
                bar.classList.add('error');
                btn.disabled = false;
                btn.innerHTML = '&#9889; Generate Document';
                showAlert('error', `Generation failed: ${data.error || data.message}`);
                if (ws) { ws.close(); ws = null; }
            }
        }

        /* ========== DOWNLOAD ========== */
        function downloadDocument() {
            if (downloadUrl) {
                window.location.href = downloadUrl;
            }
        }

        /* ========== HISTORY ========== */
        function addToHistory(action, url) {
            const labels = {
                resume: 'Base Resume',
                resume_tailored: 'Tailored Resume',
                cover_letter: 'Cover Letter',
            };
            genHistory.unshift({
                action: labels[action] || action,
                time: new Date().toLocaleString(),
                url: url,
            });
            if (genHistory.length > 10) genHistory = genHistory.slice(0, 10);
            localStorage.setItem('aihawk_history', JSON.stringify(genHistory));
            renderHistory();
        }

        function renderHistory() {
            const list = document.getElementById('historyList');
            if (genHistory.length === 0) {
                list.innerHTML = '<p style="color: var(--gray-400); text-align: center; padding: 20px;">No documents generated yet.</p>';
                return;
            }
            list.innerHTML = genHistory.map(h => `
                <div class="history-item">
                    <div class="history-info">
                        <h4>${escapeHtml(h.action)}</h4>
                        <p>${escapeHtml(h.time)}</p>
                    </div>
                    ${h.url ? `<a href="${h.url}" class="btn btn-outline btn-sm" style="text-decoration:none;">Download</a>` : ''}
                </div>
            `).join('');
        }

        function clearHistory() {
            genHistory = [];
            localStorage.removeItem('aihawk_history');
            renderHistory();
        }
