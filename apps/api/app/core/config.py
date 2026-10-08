from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Values that were once the shipped defaults. They are rejected in production
#: by name as well as by length, because a placeholder that happens to be long
#: enough is still a placeholder.
_INSECURE_SECRET_KEYS = frozenset(
    {
        "",
        "change-me-in-production",
        "development-only-change-this-secret",
        "changeme",
        "secret",
    }
)

#: Cookie names that look like a session identifier rather than a name. A
#: browser sends ``__Host-``-style cookies more defensively and frameworks
#: treat them as first-party, which is what an auth cookie should be.
_INSECURE_COOKIE_NAMES = frozenset({"session", "sessionid", "session_id", "sid", "token"})


class Settings(BaseSettings):
    app_name: str = "StudyOS API"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://studyos:studyos@localhost:5432/studyos"
    database_admin_url: str = "postgresql+asyncpg://studyos:studyos@localhost:5432/postgres"
    #: Token signing key. There is deliberately no usable default: a shipped
    #: secret means anyone who reads the repository can mint a session for any
    #: user, so production refuses to start without an explicit value.
    secret_key: str = Field(default="", min_length=16)
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    cookie_name: str = "studyos_session"
    upload_dir: Path = Path("./data/uploads")
    max_upload_size: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    log_level: str = "INFO"

    # -- Connection pooling --------------------------------------------------
    #
    # These were previously left to SQLAlchemy's defaults, which size a pool
    # for a short-lived request workload. This application's dominant workload
    # is long-running agent runs, so the pool is sized explicitly and its
    # relationship to Postgres ``max_connections`` is documented here rather
    # than discovered during an incident.
    #
    # Budget: ``(pool_size + max_overflow) * processes <= max_connections``,
    # leaving headroom for migrations and admin sessions. At the defaults below
    # that allows ~5 API processes against a 100-connection server.
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    #: How long a caller waits for a connection before the request fails. Kept
    #: short deliberately: a queued agent request is better told to retry than
    #: left holding a worker for 30 seconds.
    db_pool_timeout: float = Field(default=10.0, ge=1.0, le=120.0)
    #: Recycle below typical proxy/server idle timeouts so a stale connection is
    #: replaced rather than surfacing as a mid-request error.
    db_pool_recycle: int = Field(default=1800, ge=60, le=86400)

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
    #: Ceiling on one call's completion tokens. Distinct from ``llm_max_output_tokens``
    #: (a request), this is the run's own limit (a budget), and it is what stops a
    #: model that decides to write an essay inside a "draft this outline" step.
    agent_max_output_tokens_per_step: int = Field(default=4000, ge=256, le=64000)
    #: Ceiling on prompt tokens for one call. The prompt is assembled from the
    #: student's own brief and the plan, so a large assignment could otherwise
    #: bill for a context the model will not use.
    agent_max_input_tokens_per_step: int = Field(default=32000, ge=256, le=400000)
    #: Ceiling on tokens for a whole run. The iteration budget alone does not
    #: bound spend: forty steps of five thousand tokens each is not forty cheap
    #: steps.
    agent_max_tokens_per_run: int = Field(default=400_000, ge=1_000, le=10_000_000)
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

    # ------------------------------------------------------------------
    # Model pricing.
    #
    # ``{"model-name": {"prompt": 0.005, "completion": 0.015}}`` in dollars per
    # 1,000 tokens. A model absent from this map is *unpriced*, not free, and a
    # run on an unpriced model records no cost.
    #
    # It is configuration rather than a constant because prices change and a
    # deployment may point at a self-hosted or discounted endpoint. Leaving it
    # empty is a valid, honest configuration; what is not valid is a cost guardrail
    # that silently assumes unknown models are free, which is how the agent's
    # cost limit came to never firing.
    # ------------------------------------------------------------------
    llm_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: What to do when a run's selected model has no entry in ``llm_pricing``.
    #: ``record`` keeps the run working and reports it as uncosted. ``refuse``
    #: makes an unpriced deployment unusable, which is the correct choice for
    #: anyone who needs the guarantee to be real rather than advisory.
    llm_unpriced_model_policy: Literal["record", "refuse"] = "record"

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

    def validate_for_startup(self) -> None:
        """Refuse to start a production process on unsafe configuration.

        Every finding here is a setting whose insecure default is convenient in
        development and catastrophic in production. Failing at startup is the
        only reliable moment: a value that is merely *logged* as a warning has
        a habit of being read and ignored, and a deployed container that starts
        cleanly is the signal an operator is watching for.
        """
        if not self.is_production:
            return

        problems: list[str] = []

        if not self.secret_key:
            problems.append(
                "SECRET_KEY is unset. Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )
        elif self.secret_key in _INSECURE_SECRET_KEYS or len(self.secret_key) < 32:
            problems.append(
                "SECRET_KEY is a known placeholder or shorter than 32 characters. "
                "Anyone who can read the repository could sign their own session."
            )

        if not self.cookie_secure:
            problems.append(
                "COOKIE_SECURE is false, so the session cookie is sent over plain "
                "HTTP. Set it to true and terminate TLS in front of the API."
            )

        if "*" in self.cors_origin_list:
            problems.append(
                "CORS_ORIGINS contains '*'. Credentials cannot be combined with a "
                "wildcard origin safely, so list the allowed origins explicitly."
            )

        if self.cookie_name in _INSECURE_COOKIE_NAMES:
            problems.append(
                f"COOKIE_NAME is {self.cookie_name!r}. A cookie named like a session "
                "id invites a fixation attack."
            )

        if problems:
            raise RuntimeError(
                "Refusing to start in production with an unsafe configuration:\n"
                + "\n".join(f"  - {problem}" for problem in problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
