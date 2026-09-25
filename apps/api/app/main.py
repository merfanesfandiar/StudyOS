from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware
from app.modules.assignments import router as assignments_router
from app.modules.auth import router as auth_router
from app.modules.courses import router as courses_router
from app.modules.dashboard import router as dashboard_router
from app.modules.documents import router as documents_router
from app.modules.health import router as health_router
from app.modules.notifications import router as notifications_router
from app.storage import get_storage

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    get_storage()
    yield


app = FastAPI(
    title="StudyOS API",
    version="0.1.0",
    description="Phase 1 API for the StudyOS academic workspace.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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
app.include_router(documents_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"name": "StudyOS API", "docs": "/docs"}
