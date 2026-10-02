"""
T06 Focused Tests — Forecast Persistence + API.

Coverage:
A. Persistence mapping — T04 output maps correctly to RateForecast.
B. Per-series champion — MA(3) lane remains MA(3), not overwritten by global MA(4).
C. Evidence snapshot — persisted MAE/RMSE/sMAPE/eval_points match generation.
D. Freshness — stale observation persists input_freshness='stale'.
E. Generation-time trap — recent generated_at cannot make stale source fresh.
F. Safety — live_decision_eligible=False where source is stale.
G. Idempotency — same evidence re-run does not create duplicates.
H. New observation — new obs_date produces a new distinguishable row.
I. Latest retrieval — returns correct most-recent epoch forecast.
J. Series isolation — no cross-lane contamination.
K. API authentication — endpoints are protected.
L. API response structure — forecast / evidence / provenance / safety.
M. No GPT requirement — generation path works with zero Azure calls.
N. Financial precision — round-trip of predicted_rate is stable.
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.freight_rate import FreightRate
from app.models.rate_forecast import RateForecast
from app.services.forecast_persistence import ForecastPersistenceService, _determine_freshness


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_freight_rates(
    db: AsyncSession,
    source: str,
    trade_lane: str,
    container_type: str,
    n: int = 31,
    base_rate: float = 1000.0,
    start_date: date | None = None,
) -> list[FreightRate]:
    """Insert n consecutive daily FreightRate rows for one series."""
    if start_date is None:
        start_date = date(2025, 1, 1)
    rows = []
    for i in range(n):
        rows.append(
            FreightRate(
                source=source,
                trade_lane=trade_lane,
                container_type=container_type,
                origin_port="Test",
                dest_region="Test",
                rate_usd=base_rate + i * 5,
                rate_date=start_date + timedelta(days=i),
            )
        )
    for r in rows:
        db.add(r)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# D. Freshness helper unit test (no DB needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_freshness_recent_date_is_fresh():
    fresh_date = date.today() - timedelta(days=3)
    freshness, eligible = _determine_freshness(fresh_date)
    assert freshness == "fresh"
    assert eligible is True


def test_freshness_old_date_is_stale():
    stale_date = date.today() - timedelta(days=60)
    freshness, eligible = _determine_freshness(stale_date)
    assert freshness == "stale"
    assert eligible is False


# E. Generation-time trap
def test_freshness_does_not_use_generated_at():
    """Freshness derives from source observation date, never from generation timestamp."""
    stale_source = date(2026, 9, 2)
    freshness, eligible = _determine_freshness(stale_source, datetime(2026, 10, 3, tzinfo=timezone.utc))
    # Even though we "generate" right now, the source is old
    assert freshness == "stale"
    assert eligible is False


# ─────────────────────────────────────────────────────────────────────────────
# DB Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_persistence_mapping(db_session: AsyncSession):
    """A. T04 output maps correctly to a persisted RateForecast row."""
    _make_freight_rates(db_session, "SCFI", "TestLane", "20ft", n=31)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "TestLane", "20ft")

    assert row is not None
    assert row.source == "SCFI"
    assert row.trade_lane == "TestLane"
    assert row.container_type == "20ft"
    assert row.predicted_rate is not None
    assert row.model_name in ["Naive", "MA(2)", "MA(3)", "MA(4)", "Drift"]
    assert row.forecast_horizon == 1
    assert row.evaluation_points > 0
    assert row.backtest_mae >= 0
    assert row.backtest_rmse >= 0
    assert row.history_observations == 31
    assert row.data_readiness == "MINIMAL"


@pytest.mark.asyncio
async def test_per_series_champion_not_overwritten_by_global_default(db_session: AsyncSession):
    """
    B. The persisted model_name must be the per-series T04 champion, not the
    global MA(4) default.  We seed a series where MA(3) or another model wins,
    confirm the persisted model reflects the actual backtest winner.
    """
    # Seed a rising series (consistent trend makes lags competitive)
    _make_freight_rates(db_session, "SCFI", "ChampionTestLane", "20ft", n=31, base_rate=1000.0)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "ChampionTestLane", "20ft")

    assert row is not None
    # The stored model_name must be whichever model actually won per-backtest —
    # not hardcoded to MA(4)
    from app.services.baseline_forecasting import BaselineForecastingService
    from app.services.forecast_dataset import ForecastDatasetBuilder

    builder = ForecastDatasetBuilder(db_session)
    dataset = await builder.build_dataset("SCFI", "ChampionTestLane", "20ft")
    forecaster = BaselineForecastingService(initial_train_size=15)
    report = forecaster.backtest(dataset)

    assert row.model_name == report.champion_model, (
        f"Persisted model '{row.model_name}' ≠ actual champion '{report.champion_model}'"
    )


@pytest.mark.asyncio
async def test_evidence_snapshot_matches_generation(db_session: AsyncSession):
    """C. Persisted MAE / RMSE / sMAPE / eval_points match what the backtest reported."""
    _make_freight_rates(db_session, "SCFI", "EvidenceTestLane", "40ft", n=31)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "EvidenceTestLane", "40ft")

    from app.services.baseline_forecasting import BaselineForecastingService
    from app.services.forecast_dataset import ForecastDatasetBuilder

    builder = ForecastDatasetBuilder(db_session)
    dataset = await builder.build_dataset("SCFI", "EvidenceTestLane", "40ft")
    forecaster = BaselineForecastingService(initial_train_size=15)
    report = forecaster.backtest(dataset)
    champion_result = next(r for r in report.results if r.model_name == report.champion_model)

    assert abs(row.backtest_mae - champion_result.metrics.mae) < 0.001
    assert abs(row.backtest_rmse - champion_result.metrics.rmse) < 0.001
    assert row.evaluation_points == champion_result.metrics.evaluation_points
    assert row.backtest_smape == champion_result.metrics.smape
    assert row.backtest_directional_accuracy == champion_result.metrics.directional_accuracy_pct
    assert row.data_readiness == dataset.metadata.readiness
    assert row.latest_observation_date == dataset.observations[-1].date


@pytest.mark.asyncio
async def test_freshness_persisted_correctly_for_stale_data(db_session: AsyncSession):
    """D & F. Stale source observation → stale persisted, live_decision_eligible=False."""
    # Start date far in the past → stale
    _make_freight_rates(
        db_session, "SCFI", "StaleLane", "20ft", n=31,
        start_date=date(2025, 1, 1)
    )
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "StaleLane", "20ft")

    assert row.input_freshness == "stale"
    assert row.live_decision_eligible is False
    assert row.warning is not None


@pytest.mark.asyncio
async def test_idempotency_no_duplicates(db_session: AsyncSession):
    """G. Generating twice from identical source evidence produces exactly ONE row."""
    _make_freight_rates(db_session, "SCFI", "IdemLane", "20ft", n=31)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row1 = await svc.generate_and_persist_series("SCFI", "IdemLane", "20ft")
    row2 = await svc.generate_and_persist_series("SCFI", "IdemLane", "20ft")

    assert row1 is not None
    assert row2 is not None
    # Same idempotency key → same primary key (upserted)
    assert row1.id == row2.id

    # Confirm only one row exists in DB
    from sqlalchemy import select, func
    count = await db_session.scalar(
        select(func.count()).where(
            RateForecast.source == "SCFI",
            RateForecast.trade_lane == "IdemLane",
            RateForecast.container_type == "20ft",
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_new_observation_creates_new_row(db_session: AsyncSession):
    """H. A new source observation creates a distinguishable new forecast row."""
    # First batch
    _make_freight_rates(db_session, "SCFI", "NewObsLane", "20ft", n=31, start_date=date(2025, 1, 1))
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row1 = await svc.generate_and_persist_series("SCFI", "NewObsLane", "20ft")
    assert row1 is not None
    old_obs_date = row1.latest_observation_date

    # Add one new observation (new latest_observation_date)
    db_session.add(FreightRate(
        source="SCFI", trade_lane="NewObsLane", container_type="20ft",
        origin_port="Test", dest_region="Test",
        rate_usd=9999.0, rate_date=date(2025, 2, 1),
    ))
    await db_session.commit()

    row2 = await svc.generate_and_persist_series("SCFI", "NewObsLane", "20ft")
    assert row2 is not None
    assert row2.latest_observation_date > old_obs_date
    # Different epoch → different row
    assert row1.id != row2.id

    # Both rows exist — historical auditability preserved
    from sqlalchemy import select, func
    count = await db_session.scalar(
        select(func.count()).where(
            RateForecast.source == "SCFI",
            RateForecast.trade_lane == "NewObsLane",
            RateForecast.container_type == "20ft",
        )
    )
    assert count == 2


@pytest.mark.asyncio
async def test_latest_retrieval_returns_newest(db_session: AsyncSession):
    """I. get_latest_forecasts returns the most-recent epoch per series."""
    # Seed two epochs manually
    _make_freight_rates(db_session, "SCFI", "LatestLane", "20ft", n=31, start_date=date(2025, 1, 1))
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    await svc.generate_and_persist_series("SCFI", "LatestLane", "20ft")

    # Add newer observation
    db_session.add(FreightRate(
        source="SCFI", trade_lane="LatestLane", container_type="20ft",
        origin_port="Test", dest_region="Test",
        rate_usd=1500.0, rate_date=date(2025, 2, 15),
    ))
    await db_session.commit()
    await svc.generate_and_persist_series("SCFI", "LatestLane", "20ft")

    latest = await svc.get_latest_forecasts(
        source="SCFI", trade_lane="LatestLane", container_type="20ft"
    )
    assert len(latest) == 1
    assert latest[0].latest_observation_date == date(2025, 2, 15)


@pytest.mark.asyncio
async def test_series_isolation(db_session: AsyncSession):
    """J. Generating for lane A does not affect lane B results."""
    _make_freight_rates(db_session, "SCFI", "IsoLaneA", "20ft", n=31, base_rate=1000.0)
    _make_freight_rates(db_session, "SCFI", "IsoLaneB", "20ft", n=31, base_rate=5000.0)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row_a = await svc.generate_and_persist_series("SCFI", "IsoLaneA", "20ft")
    row_b = await svc.generate_and_persist_series("SCFI", "IsoLaneB", "20ft")

    assert row_a is not None and row_b is not None
    assert row_a.trade_lane == "IsoLaneA"
    assert row_b.trade_lane == "IsoLaneB"
    assert row_a.id != row_b.id
    # Predicted rates should differ given different base_rate seeds
    assert float(row_a.predicted_rate) != float(row_b.predicted_rate)


@pytest.mark.asyncio
async def test_financial_precision_roundtrip(db_session: AsyncSession):
    """N. predicted_rate round-trips correctly through Numeric(12, 2)."""
    _make_freight_rates(db_session, "SCFI", "PrecisionLane", "20ft", n=31, base_rate=1234.567)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "PrecisionLane", "20ft")

    assert row is not None
    # Numeric(12,2) means at most 2 decimal places
    rate_val = float(row.predicted_rate)
    rounded = round(rate_val, 2)
    assert abs(rate_val - rounded) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# K & L. API tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_requires_authentication(client: AsyncClient):
    """K. Forecast endpoints are protected — no key → 401."""
    resp = await client.get("/api/v1/forecasts")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_latest_returns_evidence_structure(
    authenticated_client: AsyncClient, db_session: AsyncSession
):
    """L. API response includes forecast / evidence / provenance / safety sections."""
    _make_freight_rates(db_session, "SCFI", "APITestLane", "20ft", n=31)
    await db_session.commit()

    # Generate first via service
    svc = ForecastPersistenceService(db_session)
    await svc.generate_and_persist_all()

    resp = await authenticated_client.get("/api/v1/forecasts/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert "forecasts" in data
    assert "count" in data

    assert data["count"] == 1
    if data["count"] == 1:
        item = data["forecasts"][0]
        assert "series" in item
        assert "forecast" in item
        assert "evidence" in item
        assert "provenance" in item
        assert "safety" in item

        # Evidence fields
        ev = item["evidence"]
        assert "mae" in ev
        assert "rmse" in ev
        assert "smape" in ev
        assert "data_readiness" in ev

        # Safety
        safety = item["safety"]
        assert "live_decision_eligible" in safety
        assert "warning" in safety


@pytest.mark.asyncio
async def test_api_stale_live_decision_eligible_false(
    authenticated_client: AsyncClient, db_session: AsyncSession
):
    """F+K. Stale source data → live_decision_eligible=false in API response."""
    _make_freight_rates(
        db_session, "SCFI", "StaleAPILane", "20ft", n=31, start_date=date(2025, 1, 1)
    )
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    await svc.generate_and_persist_series("SCFI", "StaleAPILane", "20ft")

    resp = await authenticated_client.get(
        "/api/v1/forecasts", params={"trade_lane": "StaleAPILane"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    if data["count"] == 1:
        safety = data["forecasts"][0]["safety"]
        assert safety["live_decision_eligible"] is False


@pytest.mark.asyncio
async def test_no_gpt_requirement(db_session: AsyncSession, monkeypatch):
    """
    M. Forecast generation must work with zero Azure/OpenAI calls.
    Patch the OpenAI client to raise on any invocation — generation must still succeed.
    """
    import app.ai.openai_client as oai_module

    async def _raise(*args, **kwargs):
        raise RuntimeError("GPT should not be called during forecast generation")

    monkeypatch.setattr(oai_module.FreightPulseAIClient, "generate_structured", _raise)

    _make_freight_rates(db_session, "SCFI", "NoGPTLane", "20ft", n=31)
    await db_session.commit()

    svc = ForecastPersistenceService(db_session)
    row = await svc.generate_and_persist_series("SCFI", "NoGPTLane", "20ft")
    assert row is not None, "Forecast persistence must not require GPT"


@pytest.mark.parametrize("age_days,expected", [(0, "fresh"), (10.5, "fresh"), (11, "aging"), (14, "aging"), (21, "aging"), (21.01, "stale")])
def test_authoritative_freshness_boundaries(age_days, expected):
    from app.services.data_quality import DataQualityService
    observation = date(2026, 1, 1)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=age_days)
    t02, ratio = DataQualityService.evaluate_freight_rate_freshness(observation, now)
    t06, source_eligible = _determine_freshness(observation, now)
    assert t02 == t06 == expected
    assert ratio == pytest.approx(age_days / 7)
    assert source_eligible == (expected in ("fresh", "aging"))


@pytest.mark.asyncio
@pytest.mark.parametrize("age_days", [3, 14, 30])
async def test_t02_report_and_t06_persisted_freshness_agree(db_session, monkeypatch, age_days):
    import app.services.data_quality as quality
    cutoff = date(2026, 1, 31)
    frozen_now = datetime(2026, 1, 31, tzinfo=timezone.utc) + timedelta(days=age_days)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now

    monkeypatch.setattr(quality, "datetime", FrozenDatetime)
    _make_freight_rates(db_session, "SCFI", "Consistency", "20ft", start_date=date(2026, 1, 1))
    await db_session.commit()
    report = await quality.DataQualityService().evaluate_freight_rates(db_session)
    forecast = await ForecastPersistenceService(db_session).generate_and_persist_series("SCFI", "Consistency", "20ft")
    assert forecast.latest_observation_date == cutoff
    assert forecast.input_freshness == report.freshness_status
    from app.services.forecast_dataset import ForecastDatasetBuilder
    from app.services.baseline_forecasting import BaselineForecastingService
    dataset = await ForecastDatasetBuilder(db_session).build_dataset("SCFI", "Consistency", "20ft")
    next_step = BaselineForecastingService().forecast_next(dataset, forecast.model_name, forecast.backtest_mae)
    assert next_step.input_freshness == forecast.input_freshness
    # T04 is historical-only even with a fresh/aging source.
    assert forecast.live_decision_eligible is False
    assert forecast.warning == "Historical forecast only. Do not use for live booking decisions."


@pytest.mark.asyncio
async def test_latest_model_artifacts_and_total_order(db_session, authenticated_client):
    from sqlalchemy import select, func
    _make_freight_rates(db_session, "SCFI", "TieLane", "20ft")
    _make_freight_rates(db_session, "SCFI", "OtherLane", "40ft")
    await db_session.commit()
    svc = ForecastPersistenceService(db_session)
    seed = await svc.generate_and_persist_series("SCFI", "TieLane", "20ft")
    other = await svc.generate_and_persist_series("SCFI", "OtherLane", "40ft")
    values = {c.name: getattr(seed, c.name) for c in RateForecast.__table__.columns if c.name != "id"}
    seed.generated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Observation cutoff wins even over an old artifact generated much later.
    seed.latest_observation_date -= timedelta(days=1)
    seed.generated_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    values["generated_at"] = datetime(2026, 2, 1, tzinfo=timezone.utc)
    a = RateForecast(**{**values, "model_name": "MA(3)", "id": uuid.UUID(int=3)})
    b = RateForecast(**{**values, "model_name": "MA(4)", "id": uuid.UUID(int=4)})
    db_session.add_all([a, b])
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 4
    for _ in range(2):
        latest = await svc.get_latest_forecasts()
        assert len(latest) == 2
        assert {r.id for r in latest} == {a.id, other.id}
    # Most recently generated model wins within the same observation epoch.
    b.generated_at += timedelta(days=1)
    await db_session.commit()
    assert (await svc.get_latest_forecasts(trade_lane="TieLane"))[0].id == b.id
    # Target date then model name then UUID form the stable remaining order.
    c = RateForecast(**{**values, "model_name": "MA(3)", "forecast_for_date": values["forecast_for_date"] + timedelta(days=1), "generated_at": b.generated_at})
    db_session.add(c)
    await db_session.commit()
    assert (await svc.get_latest_forecasts(trade_lane="TieLane"))[0].id == c.id
    for endpoint in ("/api/v1/forecasts", "/api/v1/forecasts/latest"):
        response = await authenticated_client.get(endpoint)
        assert response.status_code == 200
        assert response.json()["count"] == 2
        assert {r["id"] for r in response.json()["forecasts"]} == {str(c.id), str(other.id)}
        filtered = await authenticated_client.get(endpoint, params={"source": "SCFI", "container_type": "20ft"})
        assert filtered.json()["count"] == 1
        assert filtered.json()["forecasts"][0]["id"] == str(c.id)


@pytest.mark.parametrize("model,expected", [("Naive", "1000.02"), ("MA(2)", "1000.015"), ("MA(3)", "1000.01"), ("MA(4)", "1000.01"), ("Drift", "1000.03")])
def test_baseline_monetary_arithmetic_is_decimal(model, expected):
    from app.services.baseline_forecasting import BaselineForecastingService
    result = BaselineForecastingService().predict_rate(model, [Decimal("1000.00"), Decimal("1000.01"), Decimal("1000.02")])
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)


@pytest.mark.asyncio
async def test_exact_cent_rounding_before_persistence(db_session, monkeypatch):
    _make_freight_rates(db_session, "SCFI", "ExactMoney", "20ft")
    await db_session.commit()
    from sqlalchemy import select
    rates = list((await db_session.scalars(select(FreightRate).order_by(FreightRate.rate_date))).all())
    rates[-2].rate_usd = Decimal("1000.01")
    rates[-1].rate_usd = Decimal("1000.02")
    await db_session.commit()
    svc = ForecastPersistenceService(db_session)
    real_backtest = svc._forecaster.backtest

    def ma2_champion(dataset):
        report = real_backtest(dataset)
        report.champion_model = "MA(2)"
        return report

    monkeypatch.setattr(svc._forecaster, "backtest", ma2_champion)
    row = await svc.generate_and_persist_series("SCFI", "ExactMoney", "20ft")
    assert row.predicted_rate == Decimal("1000.02")  # exact 1000.015 -> half-even cents
    assert row.latest_actual_rate == Decimal("1000.02")
    await db_session.refresh(row)
    assert isinstance(row.predicted_rate, Decimal)
    assert row.predicted_rate == Decimal("1000.02")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("GET", "/api/v1/forecasts/latest"), ("POST", "/api/v1/forecasts/generate")])
async def test_other_endpoints_require_authentication(client, method, path):
    assert (await client.request(method, path)).status_code == 401


@pytest.mark.asyncio
async def test_generate_requires_admin_and_returns_exact_contract(authenticated_client, db_session):
    assert (await authenticated_client.post("/api/v1/forecasts/generate")).status_code == 403
    from sqlalchemy import select
    from app.models.user import User
    user = await db_session.scalar(select(User).where(User.email == "authtest@freightpulse.ai"))
    user.is_admin = True
    _make_freight_rates(db_session, "SCFI", "AdminLane", "20ft")
    await db_session.commit()
    response = await authenticated_client.post("/api/v1/forecasts/generate")
    assert response.status_code == 200
    assert response.json() == {"attempted": 1, "generated": 1, "failed": 0, "status": "success", "message": "Completed forecast generation: 1 generated, 0 failed out of 1 attempted. No GPT calls were made."}
    for endpoint in ("/api/v1/forecasts", "/api/v1/forecasts/latest"):
        response = await authenticated_client.get(endpoint)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == len(data["forecasts"]) == 1
        row = data["forecasts"][0]
        assert set(row) == {"id", "series", "forecast", "evidence", "provenance", "safety"}
        assert set(row["forecast"]) == {"predicted_rate", "forecast_for_date", "model", "model_version", "horizon"}
        assert set(row["evidence"]) == {"history_observations", "evaluation_points", "mae", "rmse", "smape", "directional_accuracy", "data_readiness"}
        assert set(row["provenance"]) == {"latest_observation_date", "latest_actual_rate", "input_freshness_at_generation", "current_input_freshness", "freshness_evaluated_at", "generated_at"}
        assert set(row["safety"]) == {"live_decision_eligible", "warning"}
        assert row["forecast"]["forecast_for_date"] == "2025-02-01"
        assert row["safety"]["live_decision_eligible"] is False


@pytest.mark.asyncio
async def test_ma3_and_ma4_champions_are_preserved_per_series(db_session, monkeypatch):
    _make_freight_rates(db_session, "SCFI", "MA3Lane", "20ft")
    _make_freight_rates(db_session, "SCFI", "MA4Lane", "40ft")
    await db_session.commit()
    svc = ForecastPersistenceService(db_session)
    real_backtest = svc._forecaster.backtest

    def selected_champion(dataset):
        report = real_backtest(dataset)
        report.champion_model = "MA(3)" if dataset.metadata.trade_lane == "MA3Lane" else "MA(4)"
        return report

    monkeypatch.setattr(svc._forecaster, "backtest", selected_champion)
    result = await svc.generate_and_persist_all()
    assert result.attempted == result.generated == 2
    assert result.failed == 0
    assert {r.trade_lane: r.model_name for r in result.forecasts} == {"MA3Lane": "MA(3)", "MA4Lane": "MA(4)"}


@pytest.mark.asyncio
async def test_model_change_coexists_and_identical_rerun_refreshes_same_row(db_session, monkeypatch):
    from sqlalchemy import select, func
    _make_freight_rates(db_session, "SCFI", "ChangedModel", "20ft")
    await db_session.commit()
    svc = ForecastPersistenceService(db_session)
    real_backtest = svc._forecaster.backtest
    selected = "MA(3)"

    def chosen(dataset):
        report = real_backtest(dataset)
        report.champion_model = selected
        return report

    monkeypatch.setattr(svc._forecaster, "backtest", chosen)
    ma3 = await svc.generate_and_persist_series("SCFI", "ChangedModel", "20ft")
    selected = "MA(4)"
    ma4 = await svc.generate_and_persist_series("SCFI", "ChangedModel", "20ft")
    assert ma3.id != ma4.id
    assert ma3.latest_observation_date == ma4.latest_observation_date
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 2
    # A repeated identity updates generation time and provenance without a third artifact.
    ma4.generated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await db_session.commit()
    rate = await db_session.scalar(select(FreightRate).where(FreightRate.rate_date == ma4.latest_observation_date))
    rate.rate_usd = Decimal("2345.67")
    await db_session.commit()
    repeated = await svc.generate_and_persist_series("SCFI", "ChangedModel", "20ft")
    assert repeated.id == ma4.id
    assert repeated.latest_actual_rate == Decimal("2345.67")
    assert repeated.generated_at.year != 2020
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 2
    assert (await svc.get_latest_forecasts())[0].id == ma4.id


@pytest.mark.asyncio
async def test_read_reages_cutoff_without_mutating_fresh_generation_snapshot(db_session, authenticated_client, monkeypatch):
    import app.services.data_quality as quality
    import app.routers.forecasts as routes
    now = datetime(2026, 2, 3, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(quality, "datetime", FrozenDatetime)
    monkeypatch.setattr(routes, "datetime", FrozenDatetime)
    _make_freight_rates(db_session, "SCFI", "SnapshotLane", "20ft", start_date=date(2026, 1, 1))
    await db_session.commit()
    row = await ForecastPersistenceService(db_session).generate_and_persist_series("SCFI", "SnapshotLane", "20ft")
    assert row.input_freshness == "fresh"
    generated_at = row.generated_at
    now = datetime(2026, 3, 3, tzinfo=timezone.utc)
    for path in ("/api/v1/forecasts", "/api/v1/forecasts/latest"):
        response = await authenticated_client.get(path)
        assert response.status_code == 200
        provenance = response.json()["forecasts"][0]["provenance"]
        assert "input_freshness" not in provenance
        assert provenance["input_freshness_at_generation"] == "fresh"
        assert provenance["current_input_freshness"] == "stale"
        assert datetime.fromisoformat(provenance["freshness_evaluated_at"]) == now
        assert response.json()["forecasts"][0]["safety"]["live_decision_eligible"] is False
    await db_session.refresh(row)
    assert row.input_freshness == "fresh"
    assert row.generated_at == generated_at


async def _promote_test_admin(db_session):
    from sqlalchemy import select
    from app.models.user import User
    user = await db_session.scalar(select(User).where(User.email == "authtest@freightpulse.ai"))
    user.is_admin = True
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("successful_series", [0, 1])
@pytest.mark.parametrize("failure_mode", ["database_error", "no_artifact"])
async def test_generation_partial_and_total_failure_contract(db_session, authenticated_client, monkeypatch, successful_series, failure_mode):
    from sqlalchemy import select, func, text
    await _promote_test_admin(db_session)
    _make_freight_rates(db_session, "SCFI", "BadLane", "20ft")
    if successful_series:
        _make_freight_rates(db_session, "SCFI", "GoodLane", "20ft")
    await db_session.commit()
    real_generate = ForecastPersistenceService.generate_and_persist_series

    async def fail_one(self, source, trade_lane, container_type):
        if trade_lane == "BadLane":
            if failure_mode == "database_error":
                await self._session.execute(text("SELECT 1 / 0"))
            return None
        return await real_generate(self, source, trade_lane, container_type)

    monkeypatch.setattr(ForecastPersistenceService, "generate_and_persist_series", fail_one)
    response = await authenticated_client.post("/api/v1/forecasts/generate")
    assert response.status_code == (200 if successful_series else 500)
    status = "partial_success" if successful_series else "failure"
    attempted = 1 + successful_series
    assert response.json() == {
        "attempted": attempted, "generated": successful_series, "failed": 1,
        "status": status,
        "message": f"Completed forecast generation: {successful_series} generated, 1 failed out of {attempted} attempted. No GPT calls were made.",
    }
    assert "division" not in response.text
    assert "SELECT" not in response.text
    assert "Traceback" not in response.text
    # The failed transaction was rolled back; healthy commits survive and reads work.
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == successful_series


@pytest.mark.asyncio
async def test_generation_no_available_series_is_completed_noop(db_session, authenticated_client):
    await _promote_test_admin(db_session)
    response = await authenticated_client.post("/api/v1/forecasts/generate")
    assert response.status_code == 200
    assert response.json() == {
        "attempted": 0, "generated": 0, "failed": 0, "status": "success",
        "message": "Completed forecast generation: 0 generated, 0 failed out of 0 attempted. No GPT calls were made.",
    }


@pytest.mark.asyncio
async def test_generation_systemic_failure_keeps_safe_error_envelope(db_session, authenticated_client, monkeypatch):
    await _promote_test_admin(db_session)

    async def fail_enumeration(self):
        raise RuntimeError("sensitive internal diagnostic")

    monkeypatch.setattr(ForecastPersistenceService, "generate_and_persist_all", fail_enumeration)
    response = await authenticated_client.post("/api/v1/forecasts/generate")
    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Forecast generation failed. Check server logs."
    assert "sensitive" not in response.text


@pytest.mark.asyncio
async def test_model_version_identity_and_latest_ties(db_session, authenticated_client, monkeypatch):
    from sqlalchemy import select, func
    from app.services.baseline_forecasting import BaselineForecastingService
    _make_freight_rates(db_session, "SCFI", "VersionLane", "20ft")
    await db_session.commit()
    svc = ForecastPersistenceService(db_session)
    first = await svc.generate_and_persist_series("SCFI", "VersionLane", "20ft")
    rerun = await svc.generate_and_persist_series("SCFI", "VersionLane", "20ft")
    assert first.id == rerun.id
    assert first.model_version == BaselineForecastingService.MODEL_VERSION == "baseline-v1-decimal"
    monkeypatch.setattr(svc._forecaster, "MODEL_VERSION", "baseline-v2-test")
    second = await svc.generate_and_persist_series("SCFI", "VersionLane", "20ft")
    second_rerun = await svc.generate_and_persist_series("SCFI", "VersionLane", "20ft")
    assert second.id == second_rerun.id != first.id
    assert first.model_name == second.model_name
    assert first.latest_observation_date == second.latest_observation_date
    assert first.forecast_for_date == second.forecast_for_date
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 2
    assert (await svc.get_latest_forecasts())[0].id == second.id
    # Equal generation times use deterministic version-name ordering, not fake semantic version recency.
    first.generated_at = second.generated_at
    await db_session.commit()
    for path in ("/api/v1/forecasts", "/api/v1/forecasts/latest"):
        data = (await authenticated_client.get(path)).json()
        assert data["count"] == 1
        assert data["forecasts"][0]["id"] == str(first.id)
        assert data["forecasts"][0]["forecast"]["model_version"] == "baseline-v1-decimal"


@pytest.mark.asyncio
async def test_consolidated_migration_final_schema_and_scoped_downgrade(db_session):
    """Create the final versioned table directly; downgrade only T06 objects."""
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text, inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import settings

    _make_freight_rates(db_session, "SCFI", "MigrationLane", "20ft")
    await db_session.commit()
    seed = await ForecastPersistenceService(db_session).generate_and_persist_series("SCFI", "MigrationLane", "20ft")
    original_id = seed.id
    original_rate = seed.predicted_rate
    schema = "t06_schema_" + uuid.uuid4().hex
    root = Path(__file__).resolve().parents[1]
    filename = "a1b2c3d4e5f6_add_rate_forecasts_table.py"
    spec = importlib.util.spec_from_file_location(filename, root / "alembic" / "versions" / filename)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "a1b2c3d4e5f6"
    assert migration.down_revision == "7a3b421a2c3d"

    def apply(conn, operation):
        with Operations.context(MigrationContext.configure(conn)):
            operation()

    def verify_schema(conn):
        inspector = inspect(conn)
        actual = {c["name"]: c for c in inspector.get_columns("rate_forecasts", schema=schema)}
        expected = RateForecast.__table__.columns
        assert set(actual) == set(expected.keys())
        for column in expected:
            assert actual[column.name]["nullable"] == column.nullable
            assert actual[column.name]["type"]._type_affinity is column.type._type_affinity
            for attribute in ("length", "scale", "timezone"):
                if hasattr(column.type, attribute):
                    assert getattr(actual[column.name]["type"], attribute) == getattr(column.type, attribute)
            if column.name in ("predicted_rate", "latest_actual_rate"):
                assert actual[column.name]["type"].precision == column.type.precision == 12
        assert actual["model_version"]["default"] is None
        assert actual["forecast_horizon"]["default"] == "1"
        assert actual["live_decision_eligible"]["default"] == "false"
        assert actual["generated_at"]["default"] == "now()"
        assert inspector.get_pk_constraint("rate_forecasts", schema=schema)["constrained_columns"] == ["id"]
        unique = inspector.get_unique_constraints("rate_forecasts", schema=schema)
        assert [(c["name"], c["column_names"]) for c in unique] == [(
            "uq_rate_forecast_epoch", ["source", "trade_lane", "container_type",
            "latest_observation_date", "forecast_for_date", "model_name", "model_version"]
        )]
        indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("rate_forecasts", schema=schema) if not i.get("duplicates_constraint")}
        assert indexes == {
            "idx_forecast_series": ["source", "trade_lane", "container_type"],
            "idx_forecast_obs_date": ["latest_observation_date"],
            "idx_forecast_for_date": ["forecast_for_date"],
        }

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text("CREATE TABLE sentinel_pre_t06 (id INTEGER PRIMARY KEY, marker TEXT NOT NULL)"))
                await conn.execute(text("INSERT INTO sentinel_pre_t06 VALUES (1, 'preserve')"))
                await conn.run_sync(lambda sync: apply(sync, migration.upgrade))
                await conn.run_sync(verify_schema)
                columns = ", ".join(c.name for c in RateForecast.__table__.columns)
                await conn.execute(text(f"INSERT INTO rate_forecasts ({columns}) SELECT {columns} FROM public.rate_forecasts WHERE id = :id"), {"id": original_id})
                copied_columns = ", ".join(c.name for c in RateForecast.__table__.columns if c.name not in ("id", "model_version"))
                await conn.execute(text(f"INSERT INTO rate_forecasts (id, {copied_columns}, model_version) SELECT :id, {copied_columns}, :version FROM rate_forecasts WHERE id = :original"), {"id": uuid.uuid4(), "version": "baseline-v2-test", "original": original_id})
                assert await conn.scalar(text("SELECT count(*) FROM rate_forecasts")) == 2
                assert await conn.scalar(text("SELECT predicted_rate FROM rate_forecasts WHERE id = :id"), {"id": original_id}) == original_rate
                await conn.run_sync(lambda sync: apply(sync, migration.downgrade))
                assert await conn.scalar(text("SELECT to_regclass('rate_forecasts')")) is None
                assert await conn.scalar(text("SELECT marker FROM sentinel_pre_t06 WHERE id = 1")) == "preserve"
                assert await conn.scalar(text("SELECT count(*) FROM pg_indexes WHERE schemaname = :schema AND tablename = 'rate_forecasts'"), {"schema": schema}) == 0
                await conn.run_sync(lambda sync: apply(sync, migration.upgrade))
                await conn.run_sync(verify_schema)
                assert await conn.scalar(text("SELECT marker FROM sentinel_pre_t06 WHERE id = 1")) == "preserve"
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
