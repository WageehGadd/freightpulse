from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def summarize_advisory(self, advisory_id: str):
    """Call AI-B's agreed summarize(advisory_id) integration contract."""
    try:
        from app.ai.carrier_summarizer import summarize

        return summarize(advisory_id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_route_brief(self, brief_id: str):
    """Call AI-B's agreed generate_brief(brief_id) integration contract."""
    try:
        from app.ai.route_brief_generator import generate_brief

        return generate_brief(brief_id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
