from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./freightpulse.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    API_KEY: str = "fp_live_default_secret_key"
    VESSELFINDER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    EXCHANGE_RATE_API_KEY: str = ""
    BRIEF_STORAGE_PATH: str = "./data/briefs"
    PDF_STORAGE_PATH: str = "./data/pdfs"

    # AI Configuration
    AI_MODEL: str = "gpt-4o-mini"
    AI_TEMPERATURE: float = 0.3
    AI_MAX_TOKENS: int = 1000
    AI_DAILY_BUDGET_USD: float = 10.0
    AI_MAX_REQUESTS_PER_MINUTE: int = 60
    AI_FAIL_OPEN_ON_REDIS_ERROR: bool = True

    # Prompt Versions
    AI_CARRIER_SUMMARIZER_PROMPT_VERSION: str = "v1"
    AI_RATE_OUTLOOK_PROMPT_VERSION: str = "v1"
    AI_ROUTE_BRIEF_PROMPT_VERSION: str = "v1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
