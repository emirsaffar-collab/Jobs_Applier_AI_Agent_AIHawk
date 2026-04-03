from dataclasses import dataclass
from typing import Any, Optional

from src.job import Job


@dataclass
class JobContext:
    """Container linking a Job with its application data."""
    job: Optional[Job] = None
    job_application: Optional[Any] = None
