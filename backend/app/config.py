"""Environment-based configuration. No hard-coded hosts or paths (PRD section 21)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://intel:intel@127.0.0.1:5432/inteltps"
    storage_path: str = "./data/files"

    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3:4b"
    llm_allow_hosted: bool = False

    max_upload_mb: int = 25
    ocr_enabled: bool = True
    tesseract_cmd: str = "tesseract"
    ocr_page_timeout_s: int = 60
    ocr_dpi: int = 300
    job_lease_seconds: int = 300

    secret_key: str = "change-me"  # noqa: S105 - dev default, rejected outside development
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "development" and settings.secret_key == "change-me":  # noqa: S105
        raise RuntimeError("SECRET_KEY must be set outside development")
    return settings
