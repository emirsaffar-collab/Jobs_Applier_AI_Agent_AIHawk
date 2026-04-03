"""
Embedded single-page web UI for AIHawk Resume Builder.
Returns a complete HTML page with inline CSS and JavaScript.
"""


def get_html() -> str:
    """Return the complete HTML page for the web UI."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AIHawk Resume Builder</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --primary-light: #dbeafe;
            --success: #16a34a;
            --danger: #dc2626;
            --warning: #d97706;
            --gray-50: #f9fafb;
            --gray-100: #f3f4f6;
            --gray-200: #e5e7eb;
            --gray-300: #d1d5db;
            --gray-400: #9ca3af;
            --gray-500: #6b7280;
            --gray-600: #4b5563;
            --gray-700: #374151;
            --gray-800: #1f2937;
            --gray-900: #111827;
            --radius: 8px;
            --shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
            --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--gray-50);
            color: var(--gray-800);
            line-height: 1.6;
        }

        /* Header */
        .header {
            background: white;
            border-bottom: 1px solid var(--gray-200);
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: var(--shadow);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .header h1 {
            font-size: 20px;
            font-weight: 700;
            color: var(--gray-900);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .header h1 .icon { font-size: 24px; }

        .header-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .badge {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }

        .badge-success { background: #dcfce7; color: var(--success); }
        .badge-warning { background: #fef3c7; color: var(--warning); }
        .badge-danger { background: #fee2e2; color: var(--danger); }

        /* Layout */
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px;
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
        }

        /* Cards */
        .card {
            background: white;
            border-radius: var(--radius);
            border: 1px solid var(--gray-200);
            box-shadow: var(--shadow);
            overflow: hidden;
        }

        .card-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--gray-200);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .card-header h2 {
            font-size: 16px;
            font-weight: 600;
            color: var(--gray-900);
        }

        .card-body { padding: 20px; }

        /* Forms */
        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: var(--gray-700);
            margin-bottom: 6px;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--gray-300);
            border-radius: var(--radius);
            font-size: 14px;
            color: var(--gray-800);
            background: white;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-light);
        }

        .form-group textarea {
            font-family: 'SF Mono', 'Fira Code', 'Fira Mono', monospace;
            font-size: 12px;
            resize: vertical;
            min-height: 200px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .form-help {
            font-size: 12px;
            color: var(--gray-500);
            margin-top: 4px;
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 10px 20px;
            border-radius: var(--radius);
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }

        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .btn-primary {
            background: var(--primary);
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: var(--primary-dark);
        }

        .btn-success {
            background: var(--success);
            color: white;
        }

        .btn-outline {
            background: white;
            color: var(--gray-700);
            border: 1px solid var(--gray-300);
        }

        .btn-outline:hover:not(:disabled) {
            background: var(--gray-50);
        }

        .btn-block { width: 100%; }

        .btn-group {
            display: flex;
            gap: 8px;
        }

        /* Tabs */
        .tabs {
            display: flex;
            border-bottom: 2px solid var(--gray-200);
            margin-bottom: 20px;
        }

        .tab {
            padding: 10px 16px;
            font-size: 14px;
            font-weight: 500;
            color: var(--gray-500);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
            background: none;
            border-top: none;
            border-left: none;
            border-right: none;
        }

        .tab:hover { color: var(--gray-700); }

        .tab.active {
            color: var(--primary);
            border-bottom-color: var(--primary);
        }

        /* Progress */
        .progress-container {
            padding: 20px;
            display: none;
        }

        .progress-container.active { display: block; }

        .progress-bar-track {
            height: 8px;
            background: var(--gray-200);
            border-radius: 4px;
            overflow: hidden;
            margin: 12px 0;
        }

        .progress-bar-fill {
            height: 100%;
            background: var(--primary);
            border-radius: 4px;
            transition: width 0.5s ease;
            width: 0%;
        }

        .progress-bar-fill.success { background: var(--success); }
        .progress-bar-fill.error { background: var(--danger); }

        .progress-text {
            font-size: 14px;
            color: var(--gray-600);
            text-align: center;
        }

        .progress-percent {
            font-size: 24px;
            font-weight: 700;
            color: var(--gray-800);
            text-align: center;
        }

        /* Status log */
        .status-log {
            max-height: 200px;
            overflow-y: auto;
            font-size: 13px;
            font-family: monospace;
            background: var(--gray-50);
            border: 1px solid var(--gray-200);
            border-radius: var(--radius);
            padding: 12px;
            margin-top: 12px;
        }

        .status-entry {
            padding: 4px 0;
            border-bottom: 1px solid var(--gray-100);
        }

        .status-entry:last-child { border-bottom: none; }

        .status-time {
            color: var(--gray-400);
            font-size: 11px;
            margin-right: 8px;
        }

        /* Alerts */
        .alert {
            padding: 12px 16px;
            border-radius: var(--radius);
            margin-bottom: 16px;
            font-size: 14px;
            display: none;
        }

        .alert.show { display: block; }

        .alert-error {
            background: #fee2e2;
            color: var(--danger);
            border: 1px solid #fecaca;
        }

        .alert-success {
            background: #dcfce7;
            color: var(--success);
            border: 1px solid #bbf7d0;
        }

        .alert-info {
            background: var(--primary-light);
            color: var(--primary-dark);
            border: 1px solid #93c5fd;
        }

        /* Action cards */
        .action-cards {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }

        @media (max-width: 768px) {
            .action-cards { grid-template-columns: 1fr; }
        }

        .action-card {
            padding: 16px;
            border: 2px solid var(--gray-200);
            border-radius: var(--radius);
            cursor: pointer;
            transition: all 0.2s;
            text-align: center;
        }

        .action-card:hover {
            border-color: var(--primary);
            background: var(--primary-light);
        }

        .action-card.selected {
            border-color: var(--primary);
            background: var(--primary-light);
        }

        .action-card .action-icon {
            font-size: 28px;
            margin-bottom: 8px;
        }

        .action-card .action-title {
            font-weight: 600;
            font-size: 14px;
            color: var(--gray-800);
        }

        .action-card .action-desc {
            font-size: 12px;
            color: var(--gray-500);
            margin-top: 4px;
        }

        /* History */
        .history-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid var(--gray-100);
        }

        .history-item:last-child { border-bottom: none; }

        .history-info h4 {
            font-size: 14px;
            color: var(--gray-800);
        }

        .history-info p {
            font-size: 12px;
            color: var(--gray-500);
        }

        /* Spinner */
        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid var(--gray-300);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Tooltip */
        .tooltip {
            position: relative;
        }

        .tooltip::after {
            content: attr(data-tip);
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%);
            background: var(--gray-800);
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s;
        }

        .tooltip:hover::after { opacity: 1; }

        /* Full-width section */
        .full-width {
            grid-column: 1 / -1;
        }

        /* Hidden */
        .hidden { display: none !important; }

        /* Job URL group */
        #jobUrlGroup { display: none; }
        #jobUrlGroup.show { display: block; }

        /* Example YAML button */
        .example-link {
            font-size: 12px;
            color: var(--primary);
            cursor: pointer;
            text-decoration: underline;
        }

        .example-link:hover {
            color: var(--primary-dark);
        }
    </style>
</head>
<body>
    <!-- Header -->
    <div class="header">
        <h1>
            <span class="icon">&#128640;</span>
            AIHawk Resume Builder
        </h1>
        <div class="header-actions">
            <span id="healthBadge" class="badge badge-warning">Checking...</span>
        </div>
    </div>

    <div class="container">
        <!-- Alert area -->
        <div id="alertArea">
            <div id="alertBox" class="alert"></div>
        </div>

        <div class="grid">
            <!-- Left Column: Configuration -->
            <div>
                <!-- API Configuration -->
                <div class="card" style="margin-bottom: 24px;">
                    <div class="card-header">
                        <h2>&#128273; API Configuration</h2>
                    </div>
                    <div class="card-body">
                        <div class="form-row">
                            <div class="form-group">
                                <label for="llmProvider">LLM Provider</label>
                                <select id="llmProvider" onchange="onProviderChange()">
                                    <option value="claude">Claude (Anthropic)</option>
                                    <option value="openai">OpenAI</option>
                                    <option value="gemini">Google Gemini</option>
                                    <option value="ollama">Ollama (Local)</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label for="llmModel">Model</label>
                                <select id="llmModel">
                                    <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
                                    <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
                                    <option value="claude-3-haiku-20240307">Claude 3 Haiku</option>
                                </select>
                            </div>
                        </div>
                        <div class="form-group">
                            <label for="apiKey">API Key</label>
                            <input type="password" id="apiKey" placeholder="Enter your API key...">
                            <p class="form-help">Your API key is sent directly to the generation endpoint and is not stored.</p>
                        </div>
                    </div>
                </div>

                <!-- Action Selection -->
                <div class="card" style="margin-bottom: 24px;">
                    <div class="card-header">
                        <h2>&#9889; Action</h2>
                    </div>
                    <div class="card-body">
                        <div class="action-cards">
                            <div class="action-card selected" onclick="selectAction(\'resume\')" id="action-resume">
                                <div class="action-icon">&#128196;</div>
                                <div class="action-title">Resume</div>
                                <div class="action-desc">Generate base resume</div>
                            </div>
                            <div class="action-card" onclick="selectAction(\'resume_tailored\')" id="action-resume_tailored">
                                <div class="action-icon">&#127919;</div>
                                <div class="action-title">Tailored Resume</div>
                                <div class="action-desc">Resume for a job</div>
                            </div>
                            <div class="action-card" onclick="selectAction(\'cover_letter\')" id="action-cover_letter">
                                <div class="action-icon">&#9993;</div>
                                <div class="action-title">Cover Letter</div>
                                <div class="action-desc">Tailored cover letter</div>
                            </div>
                        </div>
                        <div class="form-group" id="jobUrlGroup">
                            <label for="jobUrl">Job Posting URL</label>
                            <input type="url" id="jobUrl" placeholder="https://www.linkedin.com/jobs/view/...">
                            <p class="form-help">URL of the job posting to tailor your document to.</p>
                        </div>
                        <div class="form-group">
                            <label for="styleSelect">Resume Style</label>
                            <select id="styleSelect">
                                <option value="">Loading styles...</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Right Column: Resume Data -->
            <div>
                <div class="card" style="margin-bottom: 24px;">
                    <div class="card-header">
                        <h2>&#128221; Resume Data (YAML)</h2>
                        <span class="example-link" onclick="loadExample()">Load Example</span>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <textarea id="resumeYaml" rows="22" placeholder="Paste your resume YAML here..."></textarea>
                            <p class="form-help">Paste your resume in YAML format. Click &quot;Load Example&quot; to see the expected structure.</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Full width: Generate button and progress -->
            <div class="full-width">
                <div class="card">
                    <div class="card-body">
                        <button id="generateBtn" class="btn btn-primary btn-block" onclick="startGeneration()">
                            &#9889; Generate Document
                        </button>

                        <div id="progressContainer" class="progress-container">
                            <div class="progress-percent" id="progressPercent">0%</div>
                            <div class="progress-bar-track">
                                <div class="progress-bar-fill" id="progressBar"></div>
                            </div>
                            <div class="progress-text" id="progressText">Waiting...</div>
                            <div class="status-log" id="statusLog"></div>
                        </div>

                        <div id="downloadSection" class="hidden" style="text-align: center; margin-top: 16px;">
                            <button id="downloadBtn" class="btn btn-success" onclick="downloadDocument()">
                                &#11015; Download PDF
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- History -->
            <div class="full-width">
                <div class="card">
                    <div class="card-header">
                        <h2>&#128203; Recent Generations</h2>
                        <button class="btn btn-outline" onclick="clearHistory()" style="padding: 6px 12px; font-size: 12px;">Clear</button>
                    </div>
                    <div class="card-body" id="historyList">
                        <p style="color: var(--gray-400); text-align: center; padding: 20px;">No documents generated yet.</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // State
        let currentAction = 'resume';
        let currentJobId = null;
        let ws = null;
        let downloadUrl = null;
        let history = JSON.parse(localStorage.getItem('aihawk_history') || '[]');

        // Model options per provider
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

        // Example YAML
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

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            checkHealth();
            loadStyles();
            renderHistory();
        });

        // Health check
        async function checkHealth() {
            const badge = document.getElementById('healthBadge');
            try {
                const res = await fetch('/api/health');
                if (res.ok) {
                    badge.className = 'badge badge-success';
                    badge.textContent = 'Connected';
                } else {
                    badge.className = 'badge badge-danger';
                    badge.textContent = 'Error';
                }
            } catch {
                badge.className = 'badge badge-danger';
                badge.textContent = 'Offline';
            }
        }

        // Load styles
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
            } catch {
                select.innerHTML = '<option value="">Failed to load styles</option>';
            }
        }

        // Provider change
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

        // Action selection
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

        // Load example
        function loadExample() {
            document.getElementById('resumeYaml').value = exampleYaml;
        }

        // Show alert
        function showAlert(type, message) {
            const box = document.getElementById('alertBox');
            box.className = `alert alert-${type} show`;
            box.textContent = message;
            setTimeout(() => { box.classList.remove('show'); }, 5000);
        }

        // Add status log entry
        function addStatusLog(message) {
            const log = document.getElementById('statusLog');
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'status-entry';
            entry.innerHTML = `<span class="status-time">${time}</span>${message}`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }

        // Start generation
        async function startGeneration() {
            const apiKey = document.getElementById('apiKey').value.trim();
            const resumeYaml = document.getElementById('resumeYaml').value.trim();
            const jobUrl = document.getElementById('jobUrl').value.trim();
            const style = document.getElementById('styleSelect').value;
            const provider = document.getElementById('llmProvider').value;
            const model = document.getElementById('llmModel').value;

            // Validation
            if (!apiKey) { showAlert('error', 'Please enter your API key.'); return; }
            if (!resumeYaml) { showAlert('error', 'Please paste your resume YAML.'); return; }
            if ((currentAction === 'resume_tailored' || currentAction === 'cover_letter') && !jobUrl) {
                showAlert('error', 'Please enter a job posting URL for tailored documents.');
                return;
            }

            // Reset UI
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

                // Connect WebSocket for progress
                connectWebSocket(currentJobId);

                // Also poll as fallback
                pollStatus(currentJobId);

            } catch (err) {
                showAlert('error', `Failed to start generation: ${err.message}`);
                btn.disabled = false;
                btn.innerHTML = '&#9889; Generate Document';
                document.getElementById('progressContainer').classList.remove('active');
            }
        }

        // WebSocket connection
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
            } catch { /* Fallback to polling */ }
        }

        // Poll status fallback
        async function pollStatus(jobId) {
            const interval = setInterval(async () => {
                try {
                    const res = await fetch(`/api/status/${jobId}`);
                    const data = await res.json();
                    updateProgress(data);
                    if (data.status === 'completed' || data.status === 'failed') {
                        clearInterval(interval);
                    }
                } catch { /* continue polling */ }
            }, 2000);
        }

        // Update progress UI
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

        // Download
        function downloadDocument() {
            if (downloadUrl) {
                window.location.href = downloadUrl;
            }
        }

        // History
        function addToHistory(action, url) {
            const labels = {
                resume: 'Base Resume',
                resume_tailored: 'Tailored Resume',
                cover_letter: 'Cover Letter',
            };
            history.unshift({
                action: labels[action] || action,
                time: new Date().toLocaleString(),
                url: url,
            });
            if (history.length > 10) history = history.slice(0, 10);
            localStorage.setItem('aihawk_history', JSON.stringify(history));
            renderHistory();
        }

        function renderHistory() {
            const list = document.getElementById('historyList');
            if (history.length === 0) {
                list.innerHTML = '<p style="color: var(--gray-400); text-align: center; padding: 20px;">No documents generated yet.</p>';
                return;
            }
            list.innerHTML = history.map(h => `
                <div class="history-item">
                    <div class="history-info">
                        <h4>${h.action}</h4>
                        <p>${h.time}</p>
                    </div>
                    ${h.url ? `<a href="${h.url}" class="btn btn-outline" style="padding: 6px 12px; font-size: 12px; text-decoration: none;">Download</a>` : ''}
                </div>
            `).join('');
        }

        function clearHistory() {
            history = [];
            localStorage.removeItem('aihawk_history');
            renderHistory();
        }
    </script>
</body>
</html>'''
