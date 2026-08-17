from celery import Celery
from celery.schedules import crontab

from app.config import settings


celery_app = Celery(
    "freightpulse",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.ai_generation",
        "app.tasks.route_brief_generation",
        "app.tasks.rate_outlook_generation",
        "app.tasks.rate_ingestion",
        "app.tasks.trend_computation",
        "app.tasks.alert_evaluation",
        "app.tasks.orchestration"
    ],
)

celery_app.conf.update(
    timezone="Africa/Cairo",
    enable_utc=True,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

celery_app.conf.beat_schedule = {
    "run-daily-pipeline": {
        "task": "app.tasks.orchestration.trigger_daily_pipeline",
        "schedule": crontab(hour=2, minute=0),
    },
}
