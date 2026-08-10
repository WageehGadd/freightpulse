from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    API_KEY: str
    VESSELFINDER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    EXCHANGE_RATE_API_KEY: str = ""


    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()