from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from database import Base, engine

# ---------------------------------------------------------------------------
# Import all models so that Alembic / create_all sees them
# ---------------------------------------------------------------------------
import models.audit_log  # noqa: F401
import models.host  # noqa: F401
import models.user  # noqa: F401

# ---------------------------------------------------------------------------
# Import routers
# ---------------------------------------------------------------------------
from routers import auth, console, containers, images, metrics, networks, storage

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
    """Create database tables on startup (dev/test convenience)."""
    logger.info("startup", env=settings.APP_ENV)
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("shutdown")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="lxdash API",
    description="REST + WebSocket API for managing LXD containers.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    # Never expose internal detail in default 422/500 responses
    openapi_url="/openapi.json",
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
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.APP_ENV == "development",
        log_config=None,  # structlog handles logging
    )
