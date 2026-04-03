"""
Celery application configuration.

The broker and result backend are read from ``app.config.settings`` so they
can be overridden via environment variables without touching source code.

Default (single-user / development):
    broker  = memory://          (in-process, no Redis required)
    backend = db+sqlite:///./celery_results.db

Production (multi-worker):
    CELERY_BROKER_URL=redis://localhost:6379/0
    CELERY_RESULT_BACKEND=redis://localhost:6379/1
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "aihawk",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.document_tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Retry / reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry – keep results for 24 hours
    result_expires=86400,
    # Concurrency – single worker thread is fine for the default in-memory broker
    worker_concurrency=1,
    # Logging
    worker_hijack_root_logger=False,
)
