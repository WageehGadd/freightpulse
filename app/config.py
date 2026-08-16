from __future__ import annotations
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    VESSELFINDER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    EXCHANGE_RATE_API_KEY: str = ""

    # AI Prompt Versions
    AI_CARRIER_SUMMARIZER_PROMPT_VERSION: str = "v1"
    AI_RATE_OUTLOOK_PROMPT_VERSION: str = "v1"
    AI_ROUTE_BRIEF_PROMPT_VERSION: str = "v1"

    # AI Model Configuration
    AI_MODEL: str = "gpt-4o-mini"
    AI_TEMPERATURE: float = 0.3
    AI_MAX_TOKENS: int = 1000

    # AI Budget and Telemetry Safeguards
    AI_DAILY_BUDGET_USD: float = 0.0  # 0.0 = unlimited
    AI_MAX_REQUESTS_PER_MINUTE: int = 0  # 0 = unlimited
    AI_FAIL_OPEN_ON_REDIS_ERROR: bool = True



    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
