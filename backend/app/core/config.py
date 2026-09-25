from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NEXUS API"
    environment: str = "local"
    debug: bool = False
    database_url: str = "postgresql+psycopg://nexus:nexus@localhost:5432/nexus"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
