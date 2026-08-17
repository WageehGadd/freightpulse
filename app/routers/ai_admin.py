from __future__ import annotations

import logging
from typing import Any, Dict

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai.budget_guard import BudgetGuard
from app.ai.prompts import registry
from app.ai.telemetry import AITelemetry
from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_admin_user, get_current_user
from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Management"], dependencies=[Depends(RateLimiter())])


class AIHealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    redis_status: str
    active_prompts: Dict[str, str]
    budget: Dict[str, Any]


class AIPromptMetadataResponse(BaseModel):
    features: Dict[str, Dict[str, Any]]


@router.get("/health", response_model=AIHealthResponse)
async def get_ai_health(
    current_user: User = Depends(get_current_admin_user),  # noqa: ARG001
):
    """Inspect AI provider status, active prompt configurations, and budget utilization."""
    redis_status = "connected"
    try:
        redis = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
        await redis.aclose()
    except Exception:  # noqa: BLE001
        redis_status = "disconnected"

    actual_usd, reserved_usd, committed_usd = await BudgetGuard.get_budget_status()

    daily_budget = getattr(settings, "AI_DAILY_BUDGET_USD", 0.0)
    utilization_pct = 0.0
    if daily_budget > 0.0:
        utilization_pct = round((committed_usd / daily_budget) * 100.0, 2)

    return AIHealthResponse(
        status="healthy" if redis_status == "connected" else "degraded",
        provider="openai",
        model=getattr(settings, "AI_MODEL", "gpt-4o-mini"),
        redis_status=redis_status,
        active_prompts={
            "carrier_summarizer": getattr(settings, "AI_CARRIER_SUMMARIZER_PROMPT_VERSION", "v1"),
            "rate_outlook": getattr(settings, "AI_RATE_OUTLOOK_PROMPT_VERSION", "v1"),
            "route_brief": getattr(settings, "AI_ROUTE_BRIEF_PROMPT_VERSION", "v1"),
        },
        budget={
            "daily_budget_usd": daily_budget,
            "max_requests_per_minute": getattr(settings, "AI_MAX_REQUESTS_PER_MINUTE", 0),
            "actual_spend_usd": round(actual_usd, 6),
            "reserved_spend_usd": round(reserved_usd, 6),
            "committed_spend_usd": round(committed_usd, 6),
            "utilization_pct": utilization_pct,
        },
    )


@router.get("/metrics")
async def get_ai_metrics(
    current_user: User = Depends(get_current_admin_user),  # noqa: ARG001
):
    """Retrieve aggregated daily AI telemetry, token consumption, and cost breakdown."""
    return await AITelemetry.get_daily_metrics()


@router.get("/prompts", response_model=AIPromptMetadataResponse)
async def get_ai_prompt_metadata(
    current_user: User = Depends(get_current_admin_user),  # noqa: ARG001
):

    """List available prompt versions and metadata without exposing raw system prompts or templates."""
    features = ["carrier_summarizer", "rate_outlook", "route_brief"]
    result: Dict[str, Dict[str, Any]] = {}

    for feat in features:
        available_versions = registry.list_versions(feat)
        active_version = registry._get_configured_version(feat)

        # Get active template metadata safely
        desc = ""
        try:
            active_prompt = registry.get_prompt(feat, active_version)
            desc = active_prompt.description
        except Exception:  # noqa: BLE001
            pass

        result[feat] = {
            "active_version": active_version,
            "available_versions": available_versions,
            "description": desc,
        }

    return AIPromptMetadataResponse(features=result)
