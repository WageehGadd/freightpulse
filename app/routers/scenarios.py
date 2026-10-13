"""
Scenario Intelligence Router (T17).
Exposes authenticated deterministic 'what-if' market rate scenarios.
Strictly non-operational and hypothetical; never triggers T14 predictive alerts.
"""
from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user
from app.models.user import User

try:
    from app.auth.rate_limit import RateLimiter
    rate_limiter_dep = [Depends(RateLimiter)]
except ImportError:
    rate_limiter_dep = []

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenarios", tags=["Scenarios"], dependencies=rate_limiter_dep)


@router.post("/evaluate", status_code=status.HTTP_200_OK)
async def evaluate_market_scenario(
    response: Response,
    source: str = Query(..., description="Exact rate source, e.g. SCFI"),
    trade_lane: str = Query(..., description="Exact trade lane, e.g. Shanghai-Rotterdam"),
    container_type: str = Query(..., description="Exact container type, e.g. 40ft"),
    scenario_request: dict = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Evaluate a deterministic rate scenario against the latest persisted exact-series forecast.
    Clients supply only the ScenarioRequest assumption (AbsoluteRate or PercentageAdjustment).
    Backend owns the factual DecisionInput, DecisionPolicy, and evaluation instant.
    Responses are strictly hypothetical, analytical only, and marked non-operational.
    """
    response.headers["Cache-Control"] = "no-store"

    try:
        from app.schemas.decision import SeriesIdentity, DecisionPolicy, DecisionInput
        from app.schemas.scenario import ScenarioRequest, ScenarioResult
        from app.services.forecast_persistence import ForecastPersistenceService
        from app.services.forecast_state import ForecastStateCollector, snapshot_forecast
        from app.services.scenario_intelligence import evaluate_scenario, ScenarioInputError
    except ImportError as err:
        logger.error("scenario_services_not_found", extra={"error": str(err)})
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Scenario intelligence service is not available on this deployment.",
        )

    # 1. Parse and validate the client's scenario assumption
    try:
        validated_request = ScenarioRequest.model_validate(scenario_request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid scenario request: {exc}",
        )

    # 2. Fetch the latest exact-series winner forecast
    series = SeriesIdentity(source=source, trade_lane=trade_lane, container_type=container_type)
    forecast_service = ForecastPersistenceService(db)
    rows = await forecast_service.get_latest_forecasts(
        source=source, trade_lane=trade_lane, container_type=container_type
    )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No persisted forecast found for series {source} | {trade_lane} | {container_type}",
        )

    if len(rows) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Exact-series selection returned multiple winner forecasts.",
        )

    row = rows[0]
    snapshot = snapshot_forecast(row)
    if snapshot.series != series:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Selected forecast does not match requested exact series.",
        )

    # 3. Collect current state and construct factual DecisionInput
    evaluated_at = datetime.now(timezone.utc)
    state_collector = ForecastStateCollector(db)
    collector_state = await state_collector.collect(snapshot, evaluated_at, expected_series=series)

    baseline_input = DecisionInput(forecast=snapshot, current_state=collector_state)
    policy = DecisionPolicy()

    # 4. Deterministic evaluation
    try:
        result: ScenarioResult = evaluate_scenario(
            baseline=baseline_input,
            request=validated_request,
            policy=policy,
            evaluated_at=evaluated_at,
        )
    except ScenarioInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scenario evaluation rejected: {exc}",
        )
    except Exception as exc:
        logger.exception("scenario_evaluation_unexpected_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error during scenario evaluation.",
        )

    # Return serialized ScenarioResult
    return result.model_dump(mode="json")
