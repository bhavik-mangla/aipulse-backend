"""
Celery application configuration.
Central Celery app instance used by workers, beat scheduler, and Flower.

Usage:
    celery -A govnotify.tasks.celery_app worker --loglevel=info --concurrency=4
    celery -A govnotify.tasks.celery_app beat --loglevel=info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from govnotify.config import get_settings
from govnotify.logging_config import setup_logging

setup_logging()
settings = get_settings()

# --- Celery App ---

app = Celery(
    "govnotify",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# --- Configuration ---

app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task behaviour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Result expiry (24 hours)
    result_expires=86400,
    # Task routing
    task_default_queue="default",
    # Retry policy defaults
    task_default_retry_delay=60,
    task_max_retries=3,
)

# --- Beat Schedule (§11.1) ---

app.conf.beat_schedule = {
    # Poll every hour to check for due sources.
    # Individual sources are gated by their own 'schedule_cron' (default: twice a day).
    # If a source fails or worker is busy, this hourly check will pick it up and retry it.
    "ingest-sources": {
        "task": "govnotify.tasks.ingest_tasks.ingest_all_sources",
        "schedule": crontab(minute=0), # Hourly check
    },
    # Pre-generate category digests (collect pre-gen summaries) - 6:30 AM IST = 1:00 AM UTC
    "generate-category-digests": {
        "task": "govnotify.tasks.digest_tasks.generate_all_category_digests",
        "schedule": crontab(hour=1, minute=0),
    },
    # Assemble and send user digests - 7:00 AM IST = 1:30 AM UTC
    "send-user-digests": {
        "task": "govnotify.tasks.digest_tasks.assemble_and_send_user_digests",
        "schedule": crontab(hour=1, minute=30),
    },
    # Maintenance - 2:00 AM IST = 20:30 UTC (previous day)
    "maintenance": {
        "task": "govnotify.tasks.maintenance_tasks.run_maintenance",
        "schedule": crontab(hour=20, minute=30),
    },
}

# --- Auto-discover tasks ---

app.autodiscover_tasks(
    [
        "govnotify.tasks.ingest_tasks",
        "govnotify.tasks.digest_tasks",
        "govnotify.tasks.process_tasks",
        "govnotify.tasks.maintenance_tasks",
    ]
)
