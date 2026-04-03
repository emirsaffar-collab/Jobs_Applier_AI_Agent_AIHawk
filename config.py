# In this file, you can set the configurations of the app.

import os
from src.utils.constants import DEBUG, ERROR, LLM_MODEL, OPENAI

#config related to logging must have prefix LOG_
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'ERROR')
LOG_SELENIUM_LEVEL = ERROR
LOG_TO_FILE = os.environ.get('LOG_TO_FILE', 'false').lower() == 'true'
LOG_TO_CONSOLE = os.environ.get('LOG_TO_CONSOLE', 'false').lower() == 'true'

MINIMUM_WAIT_TIME_IN_SECONDS = 60

JOB_APPLICATIONS_DIR = "job_applications"
JOB_SUITABILITY_SCORE = 7

JOB_MAX_APPLICATIONS = 5
JOB_MIN_APPLICATIONS = 1

LLM_MODEL_TYPE = os.environ.get('LLM_MODEL_TYPE', 'claude')
LLM_MODEL = os.environ.get('LLM_MODEL', 'claude-sonnet-4-20250514')
# Only required for OLLAMA models
LLM_API_URL = os.environ.get('LLM_API_URL', '')

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

# Web server configuration
WEB_HOST = os.environ.get('WEB_HOST', '0.0.0.0')
WEB_PORT = int(os.environ.get('PORT', os.environ.get('WEB_PORT', '8080')))
