from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def compute_rate_trends(self):
    """Call AI-A's agreed compute_all_trends() integration contract."""
    try:
        from app.ai.rate_trend_computer import compute_all_trends

        return compute_all_trends()
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def detect_rate_anomalies(self):
    """Call AI-A's agreed detect_all_anomalies() integration contract."""
    try:
        from app.ai.anomaly_detector import detect_all_anomalies

        return detect_all_anomalies()
    except Exception as exc:
        raise self.retry(exc=exc) from exc
