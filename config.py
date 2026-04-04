# In this file, you can set the configurations of the app.

import os
from src.utils.constants import ERROR

#config related to logging must have prefix LOG_
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
LOG_SELENIUM_LEVEL = ERROR
LOG_TO_FILE = os.environ.get('LOG_TO_FILE', 'false').lower() == 'true'
LOG_TO_CONSOLE = os.environ.get('LOG_TO_CONSOLE', 'true').lower() == 'true'

MINIMUM_WAIT_TIME_IN_SECONDS = int(os.environ.get('MINIMUM_WAIT_TIME_IN_SECONDS', '60'))

JOB_APPLICATIONS_DIR = "job_applications"
JOB_SUITABILITY_SCORE = int(os.environ.get('JOB_SUITABILITY_SCORE', '7'))

JOB_MAX_APPLICATIONS = int(os.environ.get('JOB_MAX_APPLICATIONS', '5'))
JOB_MIN_APPLICATIONS = int(os.environ.get('JOB_MIN_APPLICATIONS', '1'))

LLM_MODEL_TYPE = os.environ.get('LLM_MODEL_TYPE', 'claude')
LLM_MODEL = os.environ.get('LLM_MODEL', 'claude-sonnet-4-6')
# Only required for OLLAMA models
LLM_API_URL = os.environ.get('LLM_API_URL', '')

# LLM API key — set via env var for Railway/Docker, or via secrets.yaml for local use
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')

# Platform credentials via env vars (alternative to credentials.yaml)
LINKEDIN_EMAIL = os.environ.get('LINKEDIN_EMAIL', '')
LINKEDIN_PASSWORD = os.environ.get('LINKEDIN_PASSWORD', '')

# CAPTCHA solving (CAPSolver)
CAPSOLVER_API_KEY = os.environ.get('CAPSOLVER_API_KEY', '')

# Proxy rotation — comma-separated list of proxy URLs
# e.g. "http://user:pass@host1:8080,http://host2:8080"
PROXY_LIST = [p.strip() for p in os.environ.get('PROXY_LIST', '').split(',') if p.strip()]

# Recruiter outreach
RECRUITER_OUTREACH_ENABLED = os.environ.get('RECRUITER_OUTREACH_ENABLED', 'false').lower() == 'true'
RECRUITER_OUTREACH_DAILY_LIMIT = int(os.environ.get('RECRUITER_OUTREACH_DAILY_LIMIT', '20'))
RECRUITER_OUTREACH_STYLE = os.environ.get('RECRUITER_OUTREACH_STYLE', 'professional')

# Per-platform rate limits (daily applications)
RATE_LIMIT_DEFAULT = int(os.environ.get('RATE_LIMIT_DEFAULT', '80'))
RATE_LIMIT_COOLDOWN_MINUTES = float(os.environ.get('RATE_LIMIT_COOLDOWN_MINUTES', '5'))

# Two-factor authentication timeout (seconds) — how long to wait for manual 2FA completion
TWO_FA_TIMEOUT_SECONDS = int(os.environ.get('TWO_FA_TIMEOUT_SECONDS', '300'))

# Web server configuration
WEB_HOST = os.environ.get('WEB_HOST', '0.0.0.0')
WEB_PORT = int(os.environ.get('PORT', os.environ.get('WEB_PORT', '8080')))
