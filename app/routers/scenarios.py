"""Authenticated, non-operational T17 market what-if adapter."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.routers.decisions import NONBLANK_SELECTOR_PATTERN
from app.schemas.decision import DecisionPolicy
from app.schemas.scenario import ScenarioRequest, ScenarioResult
from app.services.decision_api import DecisionAPIService
from app.services.scenario_intelligence import evaluate_scenario, ScenarioInputError

router = APIRouter(prefix="/scenarios", tags=["Scenarios"], dependencies=[Depends(RateLimiter())])


@router.post("/evaluate", response_model=ScenarioResult)
async def evaluate_market_what_if(
    request: ScenarioRequest,
    response: Response,
    source: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    trade_lane: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    container_type: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),  # tenant authentication only
):
    """The client supplies only a typed hypothetical; factual input and policy are server-owned."""
    try:
        context = await DecisionAPIService(db).context(source, trade_lane, container_type)
        if context is None:
            raise HTTPException(404, "No persisted forecast exists for the requested exact series")
        result = evaluate_scenario(context.input, request, DecisionPolicy(), context.decision.evaluated_at)
    except HTTPException:
        raise
    except (ScenarioInputError, ValueError, ArithmeticError):
        raise HTTPException(500, "Scenario evaluation failed. Check server logs.") from None
    response.headers["Cache-Control"] = "no-store"
    return result
