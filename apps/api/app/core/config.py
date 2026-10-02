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

    # ------------------------------------------------------------------
    # Phase 5: the Professional Agent Runtime.
    #
    # The runtime is deliberately incapable of unrestricted action: there is no
    # setting anywhere that grants it a shell, a browser, an outbound network
    # route or a filesystem path. What these settings bound is *effort* — how
    # many steps, retries and tokens a single run may spend — so a bad plan or a
    # confused model produces a stopped, explained run rather than an invoice.
    # ------------------------------------------------------------------
    agent_enabled: bool = True
    #: Prompt version stamped on every decision so a behaviour change is
    #: attributable after the fact.
    agent_prompt_version: str = Field(default="agent_runtime_v1")
    #: Hard loop budget per run. Exceeding it fails the run with SYSTEM_ERROR.
    agent_max_iterations: int = Field(default=40, ge=1, le=500)
    #: Attempts per task, including the first. Retries use exponential backoff.
    agent_max_task_attempts: int = Field(default=3, ge=1, le=10)
    #: Consecutive task failures tolerated before the run is failed rather than
    #: retried again.
    agent_max_consecutive_failures: int = Field(default=3, ge=1, le=20)
    #: Ceiling on a run's estimated cost, checked before every provider call.
    agent_max_cost_per_run: float = Field(default=5.0, ge=0.0, le=1000.0)
    #: Ceiling on one provider call, so a single step cannot blow the budget.
    agent_max_cost_per_step: float = Field(default=1.0, ge=0.0, le=100.0)
    #: Upper bound on the assembled context for one step. Context is truncated
    #: deterministically from the least important source rather than by cutting
    #: the instruction block, so a prompt can never become instructionless.
    agent_max_context_chars: int = Field(default=24_000, ge=2_000, le=200_000)
    #: Per-step wall-clock budget.
    agent_step_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    #: A run whose heartbeat is older than this after a restart is considered
    #: orphaned and is reconciled by the recovery service.
    agent_heartbeat_timeout_seconds: float = Field(default=300.0, ge=10.0, le=3600.0)
    #: How long a pending checkpoint waits before the run is treated as blocked.
    agent_checkpoint_ttl_seconds: float = Field(default=86_400.0, ge=300.0, le=2_592_000.0)
    #: Retry backoff base in seconds; attempt N waits ``base * 2 ** (N - 1)``.
    agent_retry_backoff_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    #: Fraction of the task budget reserved for producing the artifact rather
    #: than for deciding what to do.
    agent_decision_token_ratio: float = Field(default=0.4, ge=0.1, le=0.9)
    #: Maximum artifacts persisted per run. A runaway revision loop stops here.
    agent_max_artifacts: int = Field(default=60, ge=1, le=500)
    #: When true, ``AUTONOMOUS`` runs may proceed past a REVIEW checkpoint that
    #: the task's acceptance criteria do not depend on.
    agent_allow_autonomous_review: bool = False

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
