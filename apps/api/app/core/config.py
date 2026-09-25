from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "StudyOS API"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://studyos:studyos@localhost:5432/studyos"
    database_admin_url: str = "postgresql+asyncpg://studyos:studyos@localhost:5432/postgres"
    secret_key: str = "development-only-change-this-secret"
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    cookie_name: str = "studyos_session"
    upload_dir: Path = Path("./data/uploads")
    max_upload_size: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
