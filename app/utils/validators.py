"""
Input validation helpers used across API endpoints and services.
"""
import re
from pathlib import Path
from typing import Optional

import yaml

from app.utils.logger import logger


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

_OPENAI_KEY_RE = re.compile(r"^sk-[A-Za-z0-9\-_]{20,}$")
_ANTHROPIC_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9\-_]{20,}$")
_GENERIC_KEY_RE = re.compile(r"^[A-Za-z0-9\-_\.]{10,}$")


def validate_api_key(api_key: str) -> bool:
    """
    Return True if *api_key* looks like a plausible LLM API key.
    Accepts OpenAI, Anthropic, and generic alphanumeric keys.
    """
    if not api_key or not isinstance(api_key, str):
        return False
    key = api_key.strip()
    return bool(
        _OPENAI_KEY_RE.match(key)
        or _ANTHROPIC_KEY_RE.match(key)
        or _GENERIC_KEY_RE.match(key)
    )


# ---------------------------------------------------------------------------
# YAML resume
# ---------------------------------------------------------------------------

REQUIRED_RESUME_SECTIONS = {"personal_information"}


def validate_resume_yaml(content: str) -> tuple[bool, Optional[str]]:
    """
    Parse *content* as YAML and verify it contains the minimum required
    sections for a plain-text resume.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on
    failure.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return False, f"Invalid YAML: {exc}"

    if not isinstance(data, dict):
        return False, "Resume YAML must be a mapping (dictionary) at the top level."

    missing = REQUIRED_RESUME_SECTIONS - set(data.keys())
    if missing:
        return False, f"Resume is missing required section(s): {', '.join(sorted(missing))}"

    return True, None


# ---------------------------------------------------------------------------
# Job preferences
# ---------------------------------------------------------------------------

REQUIRED_PREFERENCE_KEYS = {"positions", "locations"}


def validate_preferences(data: dict) -> tuple[bool, Optional[str]]:
    """
    Validate a job-preferences dictionary.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on
    failure.
    """
    if not isinstance(data, dict):
        return False, "Preferences must be a JSON object."

    missing = REQUIRED_PREFERENCE_KEYS - set(data.keys())
    if missing:
        return False, f"Preferences missing required key(s): {', '.join(sorted(missing))}"

    for key in ("positions", "locations"):
        val = data.get(key)
        if val is not None and not isinstance(val, list):
            return False, f"'{key}' must be a list."

    return True, None


# ---------------------------------------------------------------------------
# File size
# ---------------------------------------------------------------------------

MAX_RESUME_BYTES = 512 * 1024  # 512 KB


def validate_file_size(size_bytes: int, max_bytes: int = MAX_RESUME_BYTES) -> tuple[bool, Optional[str]]:
    """Return ``(True, None)`` if *size_bytes* ≤ *max_bytes*."""
    if size_bytes > max_bytes:
        return False, f"File too large: {size_bytes} bytes (max {max_bytes} bytes)."
    return True, None
