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
    llm_provider: str = "ollama"  # "ollama", "kimi", or "fake" (tests)
    llm_kimi_api_key: str | None = None
    llm_kimi_base_url: str = "https://api.moonshot.ai/v1"
    llm_kimi_model: str = "kimi-k2.6"
    llm_timeout_s: int = 120  # must stay below job_lease_seconds
    llm_num_ctx: int = 4096
    llm_num_predict: int = 2048
    llm_max_response_bytes: int = 2_000_000
    # Extraction caps: a huge document or response degrades to a warning, never exhausts the worker.
    extract_max_windows: int = 200
    extract_window_chars: int = 5400  # about 1,350 tokens
    extract_max_items_per_response: int = 100
    extract_max_rows_per_run: int = 2000

    max_upload_mb: int = 25
    ocr_enabled: bool = True
    tesseract_cmd: str = "tesseract"
    ocr_page_timeout_s: int = 60
    ocr_dpi: int = 300
    # Above this, a scanned page is rendered at a lower DPI (never below 100) or not OCRed at all.
    ocr_max_megapixels: int = 40
    # Spreadsheet caps: a wider sheet, or a workbook with more cells, fails with SHEET_TOO_LARGE.
    xlsx_max_columns: int = 200
    xlsx_max_cells: int = 2_000_000
    job_lease_seconds: int = 300

    secret_key: str = "change-me"  # noqa: S105 - dev default, rejected outside development
    environment: str = "development"

    # Session cookie `Secure` flag. Only plain-http local development and the tests turn it off.
    cookie_secure: bool = True
    # Header holding the real client address, set by a trusted proxy (CF-Connecting-IP behind the
    # Cloudflare tunnel). Unset: rate limits use the socket peer address; forwarded headers are
    # never trusted.
    client_ip_header: str | None = None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "development" and settings.secret_key == "change-me":  # noqa: S105
        raise RuntimeError("SECRET_KEY must be set outside development")
    if settings.environment != "development" and not settings.cookie_secure:
        raise RuntimeError("COOKIE_SECURE must be true outside development")
    return settings
