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

    # -- Phase 3: universal academic assignment intelligence -----------------
    #: The analyzer is disabled by default in the sense that it always uses the
    #: deterministic mock provider unless a real provider is configured. CI and
    #: local development therefore never need an API key or network access.
    analysis_enabled: bool = True
    #: ``mock`` needs no credentials; ``openai`` calls a compatible endpoint.
    llm_provider: Literal["mock", "openai"] = "mock"
    llm_model: str = "mock-academic-analyzer-v1"
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    llm_max_output_tokens: int = Field(default=4000, ge=256, le=32000)
    #: Upper bound on assignment text sent to a provider, so a giant upload
    #: cannot produce an unbounded prompt.
    analysis_max_input_chars: int = Field(default=60_000, ge=1_000, le=400_000)
    #: Document content is untrusted and potentially sensitive, so it is only
    #: included when explicitly enabled. Resource *metadata* is always included.
    analysis_include_document_text: bool = False
    #: Cost per 1,000 tokens, used only to record an estimate for a run.
    analysis_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)

    # ------------------------------------------------------------------
    # Phase 4: the two-model planning architecture.
    #
    # The product deliberately never names a vendor or model in the domain
    # layer. These settings map the two capability tiers onto whatever the
    # deployment actually has, and the router only ever asks for EFFICIENT or
    # ADVANCED. Pointing both tiers at the same model is a valid configuration
    # and is what the mock provider does.
    # ------------------------------------------------------------------
    llm_efficient_model: str = Field(default="mock-academic-analyzer-v1")
    llm_advanced_model: str = Field(default="mock-academic-analyzer-v1")
    llm_planner_prompt_version: str = Field(default="academic_planner_v1")
    planning_enabled: bool = Field(default=True)
    planning_max_task_count: int = Field(default=60, ge=5, le=200)
    planning_fallback_enabled: bool = Field(default=True)
    planning_effort_hours_per_point: float = Field(default=45.0, ge=5.0, le=600.0)

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
