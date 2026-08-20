"""Celery application for FreightPulse AI with daily Beat schedule.

Schedule (UTC):
- 10:00  ai.tasks.run_daily_trend_computation   (AI-1)
- 11:00  ai.tasks.run_daily_anomaly_detection   (AI-2) — after trends, so fresh
         rate_trends rows exist when anomaly_flag needs updating.
"""
import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

from ai.logging import setup_structured_logging

load_dotenv()

# Structured logging must be ready before any task executes.
setup_structured_logging()

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "freightpulse_ai",
    broker=redis_url,
    backend=redis_url,
    include=["ai.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,          # re-deliver task if worker dies mid-execution
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "compute-trends-daily-at-10": {
        "task": "ai.tasks.run_daily_trend_computation",
        # Executes daily at 10:00 AM
        "schedule": crontab(hour=10, minute=0),
    },
    "detect-anomalies-daily-at-11": {
        "task": "ai.tasks.run_daily_anomaly_detection",
        # Executes daily at 11:00 AM
        "schedule": crontab(hour=11, minute=0),
    },
}