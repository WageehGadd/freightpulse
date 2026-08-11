from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "freightpulse",
    broker=settings.REDIS_URL,
    include=[
        "app.tasks.scraping",
        "app.tasks.analysis",
        "app.tasks.ai_generation",
    ],
)

celery_app.conf.update(
    timezone="Africa/Cairo",
    enable_utc=True,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "compute-rate-trends": {
            "task": "app.tasks.analysis.compute_rate_trends",
            "schedule": crontab(hour=10, minute=0),
        },
        "detect-rate-anomalies": {
            "task": "app.tasks.analysis.detect_rate_anomalies",
            "schedule": crontab(hour=11, minute=0),
        },
    },
)
