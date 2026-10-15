"""Environment-based configuration. No hard-coded hosts or paths (PRD section 21)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://intel:intel@localhost:5432/inteltps"
    storage_path: str = "./data/files"

    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:4b"
    llm_allow_hosted: bool = False

    secret_key: str = "change-me"  # noqa: S105 - dev default, rejected outside development
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "development" and settings.secret_key == "change-me":  # noqa: S105
        raise RuntimeError("SECRET_KEY must be set outside development")
    return settings
