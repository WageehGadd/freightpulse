"""
Forecast Evaluation Router (T11).
Exposes authenticated read and execution endpoints for auditable forecast evaluations.
Extracts exact-series walk-forward evaluation metrics and persists atomically.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user, get_current_admin_user
from app.models.user import User

try:
    from app.auth.rate_limit import RateLimiter
    rate_limiter_dep = [Depends(RateLimiter)]
except ImportError:
    rate_limiter_dep = []

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts/evaluations", tags=["Forecast Evaluations"], dependencies=rate_limiter_dep)


@router.post("/run", status_code=status.HTTP_200_OK)
async def run_forecast_evaluations(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger auditable evaluation extraction and persistence across all candidate series.
    Restricted to administrators. Atomic per-series persistence using savepoints.
    """
    try:
        from app.services.forecast_evaluation_persistence import EvaluationPersistenceService
    except ImportError as err:
        logger.error("evaluation_persistence_service_unavailable", extra={"error": str(err)})
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Evaluation persistence service is not available on this deployment.",
        )

    service = EvaluationPersistenceService(db)
    try:
        results = await service.extract_and_persist_all()
        await db.commit()
        return {
            "status": "completed",
            "evaluated_series_count": len(results),
            "results": [r.model_dump(mode="json") if hasattr(r, "model_dump") else str(r) for r in results],
        }
    except Exception as exc:
        await db.rollback()
        logger.exception("forecast_evaluation_run_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Forecast evaluation run failed: {exc}",
        )


@router.get("", status_code=status.HTTP_200_OK)
async def get_forecast_evaluations(
    source: Optional[str] = Query(None, description="Exact rate source"),
    trade_lane: Optional[str] = Query(None, description="Exact trade lane"),
    container_type: Optional[str] = Query(None, description="Exact container type"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read the latest auditable evaluation result for an exact series.
    Normal user authentication.
    """
    try:
        from app.services.forecast_evaluation_persistence import EvaluationPersistenceService
    except ImportError as err:
        logger.error("evaluation_persistence_service_unavailable", extra={"error": str(err)})
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Evaluation persistence service is not available on this deployment.",
        )

    service = EvaluationPersistenceService(db)
    try:
        records = await service.get_latest_evaluations(
            source=source, trade_lane=trade_lane, container_type=container_type
        )
        return {
            "count": len(records),
            "evaluations": [r.model_dump(mode="json") if hasattr(r, "model_dump") else str(r) for r in records],
        }
    except Exception as exc:
        logger.exception("forecast_evaluation_read_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving evaluation records.",
        )
