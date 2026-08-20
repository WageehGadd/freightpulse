import pytest
from datetime import date
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert

from app.tasks.alert_evaluation import _run_alert_evaluation
from app.models.freight_rate import FreightRate
from app.models.rate_trend import RateTrend
from app.models.rate_alert import RateAlertRule, RateAlert

class FakeSessionContext:
    def __init__(self, session):
        self.session = session
    async def __aenter__(self):
        return self.session
    async def __aexit__(self, exc_type, exc, traceback):
        return False

@pytest.mark.asyncio
async def test_rate_spike_triggers(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    # Active rule
    rule = RateAlertRule(user_id=user_id, trade_lane="Lane1", alert_type="rate_spike", magnitude_pct=10.0)
    db_session.add(rule)
    await db_session.commit()

    # Trend with spike
    trend = RateTrend(trade_lane="Lane1", computed_date=today, change_7d_pct=15.0)
    db_session.add(trend)
    await db_session.commit()

    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 1

    event = (await db_session.execute(select(RateAlert))).scalars().first()
    assert event.alert_type == "rate_spike"
    assert "spiked" in event.message

    # Idempotency check
    res2 = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res2["triggered"] == 0
    count = len((await db_session.execute(select(RateAlert))).scalars().all())
    assert count == 1

@pytest.mark.asyncio
async def test_threshold_above_triggers(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    rule = RateAlertRule(user_id=user_id, trade_lane="Lane2", alert_type="threshold_above", target_usd=2000.0)
    db_session.add(rule)
    await db_session.commit()

    stmt = insert(FreightRate).values(
        source="SCFI", trade_lane="Lane2", origin_port="P", dest_region="R",
        container_type="40ft", rate_usd=2500.0, rate_date=today, week_number=40
    )
    await db_session.execute(stmt)
    await db_session.commit()

    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 1

    event = (await db_session.execute(select(RateAlert))).scalars().first()
    assert event.alert_type == "threshold_above"
    assert "above" in event.message

@pytest.mark.asyncio
async def test_non_triggering_conditions(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    rule = RateAlertRule(user_id=user_id, trade_lane="Lane3", alert_type="rate_drop", magnitude_pct=10.0)
    db_session.add(rule)

    # Change is only -5%, which is not < -10%
    trend = RateTrend(trade_lane="Lane3", computed_date=today, change_7d_pct=-5.0)
    db_session.add(trend)
    await db_session.commit()

    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 0

@pytest.mark.asyncio
async def test_missing_data_safe(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    rule = RateAlertRule(user_id=user_id, trade_lane="Lane4", alert_type="rate_spike", magnitude_pct=10.0)
    db_session.add(rule)
    await db_session.commit()

    # No RateTrend exists for Lane4 today
    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 0

@pytest.mark.asyncio
async def test_threshold_stale_data_skipped(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    rule = RateAlertRule(user_id=user_id, trade_lane="Lane5", alert_type="threshold_above", target_usd=2000.0)
    db_session.add(rule)
    await db_session.commit()

    # 3 days old - should be rejected by 48h freshness guard
    stale_date = date(2023, 10, 5)
    stmt = insert(FreightRate).values(
        source="SCFI", trade_lane="Lane5", origin_port="P", dest_region="R",
        container_type="40ft", rate_usd=2500.0, rate_date=stale_date, week_number=40
    )
    await db_session.execute(stmt)
    await db_session.commit()

    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 0

@pytest.mark.asyncio
async def test_threshold_fresh_data_edge_case(db_session, test_user):
    today = date(2023, 10, 8)
    user_id = test_user.id

    rule = RateAlertRule(user_id=user_id, trade_lane="Lane6", alert_type="threshold_below", target_usd=3000.0)
    db_session.add(rule)
    await db_session.commit()

    # 2 days old - exactly on the 48h boundary - should be accepted
    fresh_date = date(2023, 10, 6)
    stmt = insert(FreightRate).values(
        source="SCFI", trade_lane="Lane6", origin_port="P", dest_region="R",
        container_type="40ft", rate_usd=2500.0, rate_date=fresh_date, week_number=40
    )
    await db_session.execute(stmt)
    await db_session.commit()

    res = await _run_alert_evaluation(evaluation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["triggered"] == 1
