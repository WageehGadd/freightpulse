from typing import Optional
import app.ai.prompts.registry as _reg_mod
from app.ai.prompts.registry import (
    PromptRegistry,
    PromptTemplate,
    PromptVersionNotFoundError,
    registry,
)
from app.ai.prompts import carrier_summary_v1, rate_outlook_v1, route_brief_v1


def get_prompt(feature: str, version: Optional[str] = None) -> PromptTemplate:
    reg = getattr(_reg_mod, "registry", registry)
    return reg.get_prompt(feature, version)


__all__ = [
    "PromptRegistry",
    "PromptTemplate",
    "PromptVersionNotFoundError",
    "carrier_summary_v1",
    "rate_outlook_v1",
    "route_brief_v1",
    "registry",
    "get_prompt",
]
