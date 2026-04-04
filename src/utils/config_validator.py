"""Shared configuration validation logic.

Used by both the CLI (main.py) and the web server (src/web/app.py) to avoid
duplicating validation rules.
"""

EXPERIENCE_LEVELS = [
    "internship", "entry", "associate", "mid_senior_level", "director", "executive",
]
JOB_TYPES = [
    "full_time", "contract", "part_time", "temporary", "internship", "other", "volunteer",
]
DATE_FILTERS = ["all_time", "month", "week", "24_hours"]
APPROVED_DISTANCES = {0, 5, 10, 25, 50, 100}


def validate_work_preferences(data: dict) -> list[str]:
    """Validate work preferences dict. Returns a list of error strings (empty = valid)."""
    errors = []

    # Validate experience levels are booleans
    exp = data.get("experience_level", {})
    if not isinstance(exp, dict):
        errors.append("experience_level must be a dict")
    else:
        for level in EXPERIENCE_LEVELS:
            if level in exp and not isinstance(exp[level], bool):
                errors.append(f"Experience level '{level}' must be a boolean")

    # Validate job types are booleans
    jt = data.get("job_types", {})
    if not isinstance(jt, dict):
        errors.append("job_types must be a dict")
    else:
        for job_type in JOB_TYPES:
            if job_type in jt and not isinstance(jt[job_type], bool):
                errors.append(f"Job type '{job_type}' must be a boolean")

    # Validate date filters are booleans
    date = data.get("date", {})
    if not isinstance(date, dict):
        errors.append("date must be a dict")
    else:
        for df in DATE_FILTERS:
            if df in date and not isinstance(date[df], bool):
                errors.append(f"Date filter '{df}' must be a boolean")

    # Validate positions and locations are lists of strings
    for key in ["positions", "locations"]:
        val = data.get(key, [])
        if not isinstance(val, list) or not all(isinstance(item, str) for item in val):
            errors.append(f"'{key}' must be a list of strings")

    # Validate distance
    dist = data.get("distance")
    if dist not in APPROVED_DISTANCES:
        errors.append(f"distance must be one of {sorted(APPROVED_DISTANCES)}")

    # Validate blacklists are lists
    for bl in ["company_blacklist", "title_blacklist", "location_blacklist"]:
        val = data.get(bl)
        if val is None:
            continue
        if not isinstance(val, list):
            errors.append(f"'{bl}' must be a list")

    return errors
