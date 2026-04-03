"""
Job-preferences management service.

Stores and retrieves job-search preferences as a JSON blob in the database.
Each user has at most one active preferences record; saving new preferences
replaces the previous one.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.schemas import Preference, User
from app.services.resume_service import _get_or_create_user
from app.utils.logger import logger
from app.utils.validators import validate_preferences


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_preferences(db: Session, api_key: str, prefs: dict) -> Preference:
    """
    Persist *prefs* as the active job preferences for the user identified by
    *api_key*.  Replaces any existing preferences for that user.

    Raises
    ------
    ValueError
        If *prefs* fails validation.
    """
    valid, error = validate_preferences(prefs)
    if not valid:
        raise ValueError(error)

    user: User = _get_or_create_user(db, api_key)

    existing = (
        db.query(Preference)
        .filter(Preference.user_id == user.id)
        .order_by(Preference.created_at.desc())
        .first()
    )
    config_json = json.dumps(prefs)

    if existing:
        existing.config_json = config_json
        db.flush()
        logger.info("Updated preferences for user_id={} (pref_id={})", user.id, existing.id)
        return existing

    pref = Preference(user_id=user.id, config_json=config_json)
    db.add(pref)
    db.flush()
    logger.info("Saved new preferences for user_id={} (pref_id={})", user.id, pref.id)
    return pref


def get_preferences(db: Session, user_id: int) -> dict | None:
    """
    Return the most recent preferences dict for *user_id*, or ``None`` if
    none have been saved yet.
    """
    pref = (
        db.query(Preference)
        .filter(Preference.user_id == user_id)
        .order_by(Preference.created_at.desc())
        .first()
    )
    if pref is None:
        return None
    try:
        return json.loads(pref.config_json)
    except json.JSONDecodeError:
        logger.error("Corrupt preferences JSON for user_id={}", user_id)
        return None
