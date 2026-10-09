import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware
from app.modules.agent.router import router as agent_router
from app.modules.analysis.router import router as analysis_router
from app.modules.assignments import router as assignments_router
from app.modules.assignments.content_router import router as assignment_content_router
from app.modules.assignments.requirements_router import router as requirements_router
from app.modules.assignments.specification_router import router as specification_router
from app.modules.assignments.taxonomy_router import router as taxonomy_router
from app.modules.auth import router as auth_router
from app.modules.courses import router as courses_router
from app.modules.dashboard import router as dashboard_router
from app.modules.documents import router as documents_router
from app.modules.health import router as health_router
from app.modules.notifications import router as notifications_router
from app.modules.planning.router import router as planning_router
from app.storage import get_storage

logger = logging.getLogger(__name__)

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_storage()
    settings.validate_for_startup()
    await _run_recovery_sweep()
    yield


async def _run_recovery_sweep() -> None:
    """Reclaim runs a previous worker left behind before serving traffic.

    Runs are executed synchronously inside requests in this deployment, so a
    crash between requests abandons a run that may be stuck in ``RUNNING``. The
    first request to surface it would then find it while it is still stale,
    usually mid-step after the new worker has already started. Sweeping at boot
    parks such runs before the first request, so the first class of problems a
    student never sees is the one recovery exists for.

    The sweep is best-effort: a database that is not ready yet must not take the
    whole process down. It is also idempotent, so running it on every worker at
    boot is safe.
    """
    try:
        from app.db.session import SessionFactory
        from app.modules.agent import recovery

        async with SessionFactory() as db:
            report = await recovery.recover_stale_runs(db, get_settings())
            logger.info("agent_recovery_sweep done=%s", report.as_dict())
    except Exception:  # pragma: no cover - defensive boot path
        logger.exception("agent_recovery_sweep failed; the app will still start")


docs_available = settings.docs_enabled and not settings.is_production

app = FastAPI(
    title="StudyOS API",
    version="0.1.0",
    description=(
        "StudyOS API. Phase 3 adds the universal academic assignment intelligence layer: "
        "AI-assisted assignment classification, a structured and reviewable AssignmentAnalysis "
        "for every academic assignment type, specialized analyzers, analysis runs, evidence "
        "tracking, stale-analysis detection and a stable Phase 4 planning contract."
    ),
    docs_url="/docs" if docs_available else None,
    redoc_url="/redoc" if docs_available else None,
    openapi_url="/openapi.json" if docs_available else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(assignments_router)
app.include_router(requirements_router)
app.include_router(assignment_content_router)
app.include_router(taxonomy_router)
app.include_router(specification_router)
app.include_router(analysis_router)
app.include_router(planning_router)
app.include_router(agent_router)
app.include_router(documents_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    payload: dict[str, str] = {"name": "StudyOS API"}
    if docs_available:
        payload["docs"] = "/docs"
    return payload
