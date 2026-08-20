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
        "app.tasks.rate_outlook_generation",
        "app.tasks.route_brief_generation",
        "app.tasks.rate_ingestion",
        "app.tasks.trend_computation",
        "app.tasks.alert_evaluation",
        "app.tasks.orchestration",
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
        "run-daily-pipeline": {
            "task": "app.tasks.orchestration.trigger_daily_pipeline",
            "schedule": crontab(hour=2, minute=0),
        },
        "compute-rate-trends": {
            "task": "app.tasks.trend_computation.compute_rate_trends",
            "schedule": crontab(hour=10, minute=0),
        },
        "detect-rate-anomalies": {
            "task": "app.tasks.alert_evaluation.evaluate_rate_alerts",
            "schedule": crontab(hour=11, minute=0),
        },
    },
)
