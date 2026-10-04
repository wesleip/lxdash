from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Import all models so that Alembic / create_all sees them
# ---------------------------------------------------------------------------
import models.audit_log
import models.host
import models.user  # noqa: F401
from config import get_settings
from database import SessionLocal

# ---------------------------------------------------------------------------
# Import routers
# ---------------------------------------------------------------------------
from routers import (
    auth,
    bootstrap,
    console,
    containers,
    hosts,
    images,
    metrics,
    networks,
    storage,
    users,
)
from services.discord_notifier import get_discord_notifier
from services.host_service import ensure_local_host, ensure_mock_host

settings = get_settings()


# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """Set up structlog to emit structured JSON to stdout."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.APP_ENV == "development":
        # Human-readable output during local development
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # JSON in staging / production
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quieten noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_configure_logging()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tables are created via Alembic (entrypoint.sh runs `alembic upgrade head`).
    await get_discord_notifier().start()
    await _autoregister_local_host()
    logger.info("startup", env=settings.APP_ENV)
    yield
    await get_discord_notifier().stop()
    logger.info("shutdown")


async def _autoregister_local_host() -> None:
    """Adopt the local LXD daemon on boot so a fresh install is usable at once.

    Every container/image/network/storage endpoint delegates to a ``hosts``
    row; without one the whole panel is dead on arrival, even on a host whose
    LXD is fully configured. Registration is idempotent, and any failure here
    (no daemon, socket not mounted, wrong GID) is logged and swallowed — a
    missing LXD must never stop the app from booting.
    """
    db = SessionLocal()
    try:
        if settings.LXD_MOCK:
            ensure_mock_host(db)
        else:
            await ensure_local_host(db, settings.LXD_SOCKET_PATH)
    except Exception as exc:
        logger.warning("host.autoregister_failed", error=str(exc))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

_docs_enabled = settings.DOCS_ENABLED
app = FastAPI(
    title="lxdash API",
    description="REST + WebSocket API for managing LXD containers.",
    version="0.1.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    # Never expose internal detail in default 422/500 responses
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler — never leak stack traces
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", path=request.url.path, exc=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(bootstrap.router)
app.include_router(hosts.router)
app.include_router(containers.router)
app.include_router(images.router)
app.include_router(networks.router)
app.include_router(storage.router)
app.include_router(console.router)
app.include_router(metrics.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"], summary="Health check")
async def health() -> dict:
    """Return 200 OK with basic service info.  Used by load balancers and k8s probes."""
    return {"status": "ok", "version": app.version, "env": settings.APP_ENV}


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Dev entry point: binding 0.0.0.0 is intentional here so the reload server
    # is reachable from the host and from other compose services. Production
    # never goes through this path — entrypoint.sh runs uvicorn directly.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # nosec B104
        port=8000,
        reload=settings.APP_ENV == "development",
        log_config=None,  # structlog handles logging
    )
