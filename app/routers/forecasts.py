"""
Forecasts router — T06.

Endpoints:
  GET  /api/v1/forecasts        — list latest forecasts (optional filters)
  GET  /api/v1/forecasts/latest — alias for latest across all series
  POST /api/v1/forecasts/generate — (admin-only) trigger generation + persistence

Authentication:
  All endpoints require X-API-Key via get_current_user.
  The generate endpoint additionally requires admin privileges (get_current_admin_user).

Generation trigger decision:
  We expose a POST /generate endpoint consistent with the existing pattern of
  POST /rates/trends/{trend_id}/outlook — an authenticated HTTP trigger rather
  than a separate Celery task. This avoids over-engineering for T06.
  Celery integration is deferred to T08+ if scheduling is needed.

No GPT/Azure calls occur here.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_admin_user, get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.forecast import (
    ForecastEvidenceSchema,
    ForecastGenerateResponse,
    ForecastListResponse,
    ForecastProvenanceSchema,
    ForecastSafetySchema,
    ForecastSeriesSchema,
    ForecastValueSchema,
    RateForecastResponse,
)
from app.services.forecast_persistence import ForecastPersistenceService
from app.services.data_quality import DataQualityService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/forecasts", tags=["Forecasts"], dependencies=[Depends(RateLimiter())])


def _to_response(row, evaluated_at: datetime) -> RateForecastResponse:
    """Map a RateForecast ORM row to the structured API response."""
    current_freshness, _ = DataQualityService.evaluate_freight_rate_freshness(row.latest_observation_date, evaluated_at)
    return RateForecastResponse(
        id=row.id,
        series=ForecastSeriesSchema(
            source=row.source,
            trade_lane=row.trade_lane,
            container_type=row.container_type,
        ),
        forecast=ForecastValueSchema(
            forecast_for_date=row.forecast_for_date,
            predicted_rate=float(row.predicted_rate),
            model=row.model_name,
            model_version=row.model_version,
            horizon=row.forecast_horizon,
        ),
        evidence=ForecastEvidenceSchema(
            history_observations=row.history_observations,
            evaluation_points=row.evaluation_points,
            mae=row.backtest_mae,
            rmse=row.backtest_rmse,
            smape=row.backtest_smape,
            directional_accuracy=row.backtest_directional_accuracy,
            data_readiness=row.data_readiness,
        ),
        provenance=ForecastProvenanceSchema(
            latest_observation_date=row.latest_observation_date,
            latest_actual_rate=float(row.latest_actual_rate),
            input_freshness_at_generation=row.input_freshness,
            current_input_freshness=current_freshness,
            freshness_evaluated_at=evaluated_at,
            generated_at=row.generated_at,
        ),
        safety=ForecastSafetySchema(
            live_decision_eligible=row.live_decision_eligible,
            warning=row.warning,
        ),
    )


@router.get("", response_model=ForecastListResponse)
@router.get("/", response_model=ForecastListResponse, include_in_schema=False)
async def list_latest_forecasts(
    source: Optional[str] = Query(None, description="Filter by source, e.g. 'SCFI'"),
    trade_lane: Optional[str] = Query(None, description="Filter by trade lane"),
    container_type: Optional[str] = Query(None, description="Filter by container type, e.g. '20ft'"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """
    Return the latest forecast per series.

    Each forecast includes model evidence, input provenance, and safety status.
    live_decision_eligible=false when source freight data is stale.
    """
    svc = ForecastPersistenceService(db)
    rows = await svc.get_latest_forecasts(
        source=source,
        trade_lane=trade_lane,
        container_type=container_type,
    )
    evaluated_at = datetime.now(timezone.utc)
    forecasts = [_to_response(r, evaluated_at) for r in rows]
    return ForecastListResponse(forecasts=forecasts, count=len(forecasts))


@router.get("/latest", response_model=ForecastListResponse)
async def get_latest_forecasts(
    source: Optional[str] = Query(None),
    trade_lane: Optional[str] = Query(None),
    container_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # noqa: ARG001
):
    """Alias endpoint: latest forecasts across all series, with optional filtering."""
    svc = ForecastPersistenceService(db)
    rows = await svc.get_latest_forecasts(
        source=source, trade_lane=trade_lane, container_type=container_type
    )
    evaluated_at = datetime.now(timezone.utc)
    forecasts = [_to_response(r, evaluated_at) for r in rows]
    return ForecastListResponse(forecasts=forecasts, count=len(forecasts))


@router.post("/generate", response_model=ForecastGenerateResponse, status_code=200, responses={500: {"description": "All attempted series failed, or a systemic generation error occurred"}})
async def generate_forecasts(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),  # noqa: ARG001
):
    """
    (Admin-only) Generate and persist baseline forecasts for all available series.

    Uses T03 dataset builder + T04 baseline engine.
    No GPT/Azure calls occur.
    Each series uses its own T04 per-series champion — global MA(4) does NOT override.
    Idempotent: re-running with the same source evidence updates in place, no duplicates.
    """
    try:
        svc = ForecastPersistenceService(db)
        result = await svc.generate_and_persist_all()
        response.status_code = 500 if result.status == "failure" else 200
        return ForecastGenerateResponse(
            attempted=result.attempted,
            generated=result.generated,
            failed=result.failed,
            status=result.status,
            message=(
                f"Completed forecast generation: {result.generated} generated, "
                f"{result.failed} failed out of {result.attempted} attempted. No GPT calls were made."
            ),
        )
    except Exception:
        logger.exception("forecast_generation_failed")
        raise HTTPException(status_code=500, detail="Forecast generation failed. Check server logs.")
