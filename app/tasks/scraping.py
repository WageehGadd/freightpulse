import asyncio

from app.celery_app import celery_app
from app.scrapers.bunker import BunkerScraper
from app.scrapers.carrier_advisories import CarrierAdvisoryScraper
from app.scrapers.exchange_rate import ExchangeRateScraper
from app.scrapers.scfi import SCFIScraper


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_scfi(self):
    try:
        return _run(SCFIScraper().run())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_bunker(self):
    try:
        return _run(BunkerScraper().run())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def refresh_exchange_rate(self):
    try:
        return _run(ExchangeRateScraper().run())
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_carrier_advisories(self):
    try:
        return _run(CarrierAdvisoryScraper().run())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
