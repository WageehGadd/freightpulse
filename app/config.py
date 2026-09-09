from __future__ import annotations
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    VESSELFINDER_API_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-5-mini-1"
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"
    EXCHANGE_RATE_API_KEY: str = ""
    API_KEY: Optional[str] = None

    # AI Prompt Versions
    AI_CARRIER_SUMMARIZER_PROMPT_VERSION: str = "v1"
    AI_RATE_OUTLOOK_PROMPT_VERSION: str = "v1"
    AI_ROUTE_BRIEF_PROMPT_VERSION: str = "v1"

    # AI Model Configuration
    AI_MODEL: str = "gpt-5-mini"
    AI_TEMPERATURE: float = 1.0
    AI_MAX_TOKENS: int = 3500

    # AI Pricing per 1M tokens (Requires confirmation by infrastructure for exact Azure gpt-5-mini pricing)
    AI_INPUT_COST_PER_1M_TOKENS: float = 0.0
    AI_OUTPUT_COST_PER_1M_TOKENS: float = 0.0

    # AI Budget and Telemetry Safeguards
    AI_DAILY_BUDGET_USD: float = 0.0  # 0.0 = unlimited
    AI_MAX_REQUESTS_PER_MINUTE: int = 0  # 0 = unlimited
    AI_FAIL_OPEN_ON_REDIS_ERROR: bool = True

    # CORS Configuration
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]




    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
