"""Scheduler resolves safe artifacts and dispatches the registered Celery task."""
from unittest.mock import MagicMock
import pytest
from app.tasks.rate_outlook_orchestrator import _schedule
from tests.test_grounded_rate_outlook import evidence, factory, forecast, source_row

@pytest.mark.asyncio
async def test_scheduler_uses_scalar_uuid_and_stable_artifact(db_session,evidence,monkeypatch):
    from app.tasks import rate_outlook_orchestrator as scheduler
    from app.models import RateOutlook
    from sqlalchemy import select
    queue=MagicMock();monkeypatch.setattr(scheduler.generate_rate_outlook,'delay',queue)
    result=await _schedule(evidence[0].computed_date, factory(db_session))
    assert result=={'lanes':1,'skipped':0}
    row=(await db_session.execute(select(RateOutlook))).scalar_one()
    queue.assert_called_once_with(str(row.id))
    assert row.forecast_id==evidence[1].id

@pytest.mark.asyncio
async def test_scheduler_skips_ambiguous_series_without_gpt(db_session,evidence,monkeypatch):
    from app.tasks import rate_outlook_orchestrator as scheduler
    row=forecast(container='20ft');db_session.add_all([row,source_row(row)]);await db_session.commit()
    queue=MagicMock();monkeypatch.setattr(scheduler.generate_rate_outlook,'delay',queue)
    result=await _schedule(evidence[0].computed_date, factory(db_session))
    assert result=={'lanes':0,'skipped':1}
    queue.assert_not_called()
