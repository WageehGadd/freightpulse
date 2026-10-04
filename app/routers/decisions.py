"""Authenticated current decisions over existing forecasts; no generation endpoint."""
from time import perf_counter

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.decision_api import DecisionAPIResponse
from app.services.decision_api import DecisionAPIService

# Python treats U+001C..U+001F as whitespace in addition to Unicode \s.
# A matching character proves nonblankness; the selector itself stays unchanged.
NONBLANK_SELECTOR_PATTERN = r'[^\s\x1c-\x1f]'


logger = structlog.get_logger()
router = APIRouter(prefix='/decisions', tags=['Decisions'],
                   dependencies=[Depends(RateLimiter())])


@router.get('/latest', response_model=DecisionAPIResponse, responses={
    401: {'description': 'Active normal-user X-API-Key required'},
    404: {'description': 'No persisted forecast for this exact series'},
    422: {'description': 'All three nonempty exact selectors are required'},
    429: {'description': 'Existing per-user/path rate limit exceeded'},
    500: {'description': 'Sanitized integrity or infrastructure failure'},
})
async def latest_decision(
    response: Response,
    source: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN, description='Exact stored source; no normalization'),
    trade_lane: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN, description='Exact stored lane; no aliases'),
    container_type: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN, description='Exact stored container type'),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read current deterministic decision support. WITHHOLD/MONITOR are 200
    business states, not HTTP failures. Evidence availability is not accuracy.
    Exact Decimal values serialize as strings. No implicit generation or GPT.
    """
    started = perf_counter()
    try:
        result = await DecisionAPIService(db).latest(source, trade_lane, container_type)
    except Exception as exc:
        # Do not log exception text, credentials or internal evidence snapshots.
        logger.error('decision_evaluation_failed', endpoint='/api/v1/decisions/latest',
                     http_status=500, error_type=type(exc).__name__,
                     latency_ms=(perf_counter() - started) * 1000)
        raise HTTPException(500, 'Decision evaluation failed. Check server logs.') from None
    if result is None:
        logger.info('decision_forecast_absent', endpoint='/api/v1/decisions/latest',
                    http_status=404, latency_ms=(perf_counter() - started) * 1000)
        raise HTTPException(404, 'No persisted forecast exists for the requested exact series')
    response.headers['Cache-Control'] = 'no-store'
    logger.info('decision_evaluated', endpoint='/api/v1/decisions/latest', http_status=200,
        forecast_id=str(result.forecast.forecast_id), decision=result.decision.decision.value,
        actionable=result.decision.actionable,
        historical_evidence_status=result.evidence.historical_evidence_status.value,
        sample_sufficiency_status=result.evidence.sample_sufficiency_status.value,
        decision_evidence_status=result.evidence.decision_evidence_status.value,
        freshness=result.current_state.current_input_freshness,
        source_superseded=result.current_state.source_superseded,
        forecast_superseded=result.current_state.forecast_superseded,
        latency_ms=(perf_counter() - started) * 1000)
    return result
