"""Infrastructure smoke tests: logging setup, Celery beat config, DB helpers."""
from ai.celery_app import celery_app
from ai.logging import get_logger, setup_structured_logging


def test_structured_logging_setup_and_logger():
    """setup_structured_logging must be idempotent and produce usable loggers."""
    setup_structured_logging()  # second call must not raise
    logger = get_logger("test_smoke")
    logger.info("smoke_test_event", key="value")  # must not raise


def test_beat_schedule_configured():
    """Both daily AI-A jobs must be registered with correct task names."""
    schedule = celery_app.conf.beat_schedule
    assert "compute-trends-daily-at-10" in schedule
    assert "detect-anomalies-daily-at-11" in schedule
    assert schedule["compute-trends-daily-at-10"]["task"] == "ai.tasks.run_daily_trend_computation"
    assert schedule["detect-anomalies-daily-at-11"]["task"] == "ai.tasks.run_daily_anomaly_detection"


def test_database_helpers(monkeypatch):
    """init_db is idempotent; get_db yields a session and closes it cleanly."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import ai.database
    from ai.database import Base, get_db, init_db

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(ai.database, "engine", engine)
    monkeypatch.setattr(ai.database, "SessionLocal", TestingSessionLocal)

    init_db()  # create_all is a no-op when tables already exist

    gen = get_db()
    session = next(gen)
    assert session is not None
    try:
        next(gen)  # triggers the finally block → session.close()
    except StopIteration:
        pass