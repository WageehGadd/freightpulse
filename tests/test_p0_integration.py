from datetime import date, datetime, timedelta

from ai.database import FreightRate, RateAlert, RateTrend
from ai.tasks import run_daily_anomaly_detection, run_daily_trend_computation


def _seed_lane(session_factory, trade_lane: str, rates: list[float]) -> None:
    """Insert a deterministic rate series ending today."""
    session = session_factory()
    try:
        n = len(rates)
        today = date.today()
        for i, rate in enumerate(rates):
            session.add(
                FreightRate(
                    source="SCFI",
                    trade_lane=trade_lane,
                    origin_port="Shanghai",
                    dest_region="Rotterdam",
                    container_type="40ft",
                    rate_date=today - timedelta(days=n - 1 - i),
                    rate_usd=rate,
                )
            )
        session.commit()
    finally:
        session.close()


def test_empty_database_handled_gracefully(test_session_factory):
    """No freight_rates rows → tasks return zeroed counters, no crash."""
    result = run_daily_trend_computation.apply().result
    assert result == {"lanes_upserted": 0, "lanes_skipped": 0}

    result = run_daily_anomaly_detection.apply().result
    assert result["lanes_processed"] == 0
    assert result["alerts_created"] == 0


def test_trend_task_upserts_classified_rows(test_session_factory):
    """Three lanes with known patterns → three correctly classified trend rows."""
    _seed_lane(test_session_factory, "Rising-Lane",
               [1000.0 + 10.0 * i for i in range(30)])
    _seed_lane(test_session_factory, "Falling-Lane",
               [3000.0 - 15.0 * i for i in range(30)])
    _seed_lane(test_session_factory, "Stable-Lane",
               [2000.0 + (10.0 if i % 2 == 0 else -10.0) for i in range(30)])

    result = run_daily_trend_computation.apply().result
    assert result == {"lanes_upserted": 3, "lanes_skipped": 0}

    session = test_session_factory()
    try:
        trends = {t.trade_lane: t for t in session.query(RateTrend).all()}
        assert len(trends) == 3
        assert trends["Rising-Lane"].trend == "rising"
        assert trends["Falling-Lane"].trend == "falling"
        assert trends["Stable-Lane"].trend == "stable"
        assert trends["Rising-Lane"].anomaly_flag is False
    finally:
        session.close()


def test_trend_task_upsert_updates_existing_row(test_session_factory):
    """Running the task twice must UPDATE the same row, not create duplicates."""
    _seed_lane(test_session_factory, "Rising-Lane",
               [1000.0 + 10.0 * i for i in range(30)])

    run_daily_trend_computation.apply()
    run_daily_trend_computation.apply()

    session = test_session_factory()
    try:
        assert session.query(RateTrend).count() == 1
    finally:
        session.close()


def test_anomaly_task_creates_alert_and_sets_flag(test_session_factory):
    """Spike lane → rate_alerts row created + anomaly_flag set on trend row."""
    rising = [1000.0 + 10.0 * i for i in range(30)]
    rising[-1] = round(rising[-1] * 1.25, 2)
    _seed_lane(test_session_factory, "Spike-Lane", rising)

    run_daily_trend_computation.apply()
    result = run_daily_anomaly_detection.apply().result

    assert result["alerts_created"] == 1

    session = test_session_factory()
    try:
        alerts = session.query(RateAlert).all()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "rate_spike"
        assert alerts[0].trade_lane == "Spike-Lane"
        assert alerts[0].is_read is False
        assert "spiked" in alerts[0].message

        trend = session.query(RateTrend).filter_by(trade_lane="Spike-Lane").first()
        assert trend is not None
        assert trend.anomaly_flag is True
    finally:
        session.close()


def test_deduplication_blocks_duplicate_alerts(test_session_factory):
    """Same-day second run must NOT create a duplicate alert."""
    rising = [1000.0 + 10.0 * i for i in range(30)]
    rising[-1] = round(rising[-1] * 1.25, 2)
    _seed_lane(test_session_factory, "Spike-Lane", rising)

    run_daily_trend_computation.apply()
    run_daily_anomaly_detection.apply()
    second_run = run_daily_anomaly_detection.apply().result

    assert second_run["alerts_created"] == 0
    assert second_run["duplicates_skipped"] == 1

    session = test_session_factory()
    try:
        assert session.query(RateAlert).count() == 1
    finally:
        session.close()


def test_continuation_extends_event_on_new_day(test_session_factory):
    """P3 #3: anomaly on a NEW day extends the existing alert (no new row)."""
    rising = [1000.0 + 10.0 * i for i in range(30)]
    rising[-1] = round(rising[-1] * 1.25, 2)
    _seed_lane(test_session_factory, "Spike-Lane", rising)

    run_daily_trend_computation.apply()
    first_run = run_daily_anomaly_detection.apply().result
    assert first_run["alerts_created"] == 1

    # Simulate time passing: the event started 2 days ago, last activity yesterday
    session = test_session_factory()
    try:
        alert = session.query(RateAlert).first()
        alert.created_at = datetime.utcnow() - timedelta(days=2)
        alert.last_event_date = date.today() - timedelta(days=1)
        session.commit()
    finally:
        session.close()

    # New day, same anomaly detected → event must be EXTENDED, not duplicated
    second_run = run_daily_anomaly_detection.apply().result
    assert second_run["alerts_created"] == 0
    assert second_run["events_extended"] == 1

    session = test_session_factory()
    try:
        alerts = session.query(RateAlert).all()
        assert len(alerts) == 1              # still exactly one event
        assert alerts[0].duration_days == 2
        assert alerts[0].pattern_type == "sustained"
        assert alerts[0].last_event_date == date.today()
    finally:
        session.close()


def test_broken_lane_does_not_kill_batch(test_session_factory, monkeypatch):
    """One failing lane must be skipped while the rest of the batch succeeds."""
    _seed_lane(test_session_factory, "Good-Lane",
               [1000.0 + 10.0 * i for i in range(30)])
    _seed_lane(test_session_factory, "Broken-Lane",
               [2000.0 + 5.0 * i for i in range(30)])

    import ai.tasks as tasks_module

    real_compute = tasks_module.compute_trend

    def flaky_compute(trade_lane: str, rates):
        if trade_lane == "Broken-Lane":
            raise ValueError("simulated failure")
        return real_compute(trade_lane, rates)

    monkeypatch.setattr(tasks_module, "compute_trend", flaky_compute)

    result = run_daily_trend_computation.apply().result
    assert result["lanes_upserted"] == 1
    assert result["lanes_skipped"] == 1

    session = test_session_factory()
    try:
        trends = session.query(RateTrend).all()
        assert len(trends) == 1
        assert trends[0].trade_lane == "Good-Lane"
    finally:
        session.close()