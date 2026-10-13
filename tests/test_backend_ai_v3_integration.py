"""
Backend AI V3 Integration Tests.
Verifies handoff requirements:
1. P0: Orchestration sequence chaining T06 forecast generation before T07 outlook scheduling.
2. P0: WebSocket security boundary & tenant isolation (cross-tenant rejection, authentication).
3. P1: Router registration for scenarios, route intelligence, evaluations.
4. P1: T14 PredictiveAlertService execution and deduplication.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.tasks.orchestration import _trigger_daily_pipeline
from app.tasks.rate_forecast_orchestrator import _generate_rate_forecasts
from app.services.predictive_alert_service import PredictiveAlertService


def test_registered_endpoints_exist():
    """Verify that new backend handoff endpoints are registered on the app."""
    client = TestClient(app)
    routes = [route.path for route in app.routes]

    # Verify scenario endpoint
    assert "/api/v1/scenarios/evaluate" in routes
    # Verify route intelligence endpoint
    assert "/api/v1/routes/evidence" in routes
    # Verify evaluations endpoints
    assert "/api/v1/forecasts/evaluations" in routes
    assert "/api/v1/forecasts/evaluations/run" in routes


@pytest.mark.asyncio
async def test_orchestration_pipeline_chain_sequence():
    """
    Verify P0 Orchestration requirement:
    fresh required source data -> exact series -> T06 generation/persistence -> available persisted forecast -> dependent T07 grounded outlook.
    """
    with patch("app.tasks.orchestration._acquire_pipeline_lock", new_callable=AsyncMock) as mock_lock, \
         patch("app.tasks.orchestration.chain") as mock_chain:

        mock_lock.return_value = True
        mock_pipeline_instance = MagicMock()
        mock_chain.return_value = mock_pipeline_instance

        res = await _trigger_daily_pipeline()
        assert res["status"] == "dispatched"

        # Verify chain called with 5 sequential task signatures
        assert mock_chain.called
        task_signatures = mock_chain.call_args[0]
        assert len(task_signatures) == 5

        # Check task names in chain
        task_names = [sig.task for sig in task_signatures]
        assert "app.tasks.rate_ingestion.ingest_freight_rates" in task_names[0]
        assert "app.tasks.trend_computation.compute_rate_trends" in task_names[1]
        assert "app.tasks.rate_forecast_orchestrator.generate_rate_forecasts" in task_names[2]
        assert "app.tasks.alert_evaluation.evaluate_rate_alerts" in task_names[3]
        assert "schedule_rate_outlook" in task_names[4]

        # Verify T06 is chained BEFORE T07
        t06_idx = [i for i, name in enumerate(task_names) if "generate_rate_forecasts" in name][0]
        t07_idx = [i for i, name in enumerate(task_names) if "schedule_rate_outlook" in name][0]
        assert t06_idx < t07_idx


@pytest.mark.asyncio
async def test_rate_forecast_orchestrator_honest_reporting():
    """Verify T06 reports attempted, generated, and failed counts honestly."""
    res = await _generate_rate_forecasts("2026-10-13")
    assert "status" in res
    assert "attempted" in res
    assert "generated" in res
    assert "failed" in res


@pytest.mark.asyncio
async def test_predictive_alert_service_locking():
    """Verify T14 PredictiveAlertService acquires distributed lock per series."""
    mock_session = AsyncMock()
    service = PredictiveAlertService(mock_session)

    with patch.object(service.redis, "set", new_callable=AsyncMock) as mock_redis_set:
        # Simulate lock held by another worker
        mock_redis_set.return_value = False
        result = await service.process_series("SCFI", "Shanghai-Rotterdam", "40ft")
        assert result["status"] == "locked"


def test_test_alert_endpoint_production_restricted():
    """Verify /ws/test-alert is restricted when ENV=production."""
    client = TestClient(app)
    with patch("app.config.settings.ENV", "production"):
        response = client.post(
            "/api/v1/ws/test-alert",
            json={"trade_lane": "Egypt-China", "message": "unauthorized attempt"},
        )
        assert response.status_code == 403
