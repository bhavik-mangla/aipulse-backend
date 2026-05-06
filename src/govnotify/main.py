"""
FastAPI application factory - main entry point.
"""
from __future__ import annotations

import uuid
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from govnotify.config import get_settings
from govnotify.logging_config import set_correlation_id, setup_logging
from govnotify.exceptions import GovNotifyError, RateLimitExceeded

# Route imports
from govnotify.api.v1.admin import router as admin_router
from govnotify.api.v1.auth import router as auth_router
from govnotify.api.v1.categories import router as categories_router
from govnotify.api.v1.config import router as config_router
from govnotify.api.v1.notifications import router as notifications_router
from govnotify.api.v1.users import router as users_router
from govnotify.api.v1.analytics import router as analytics_router

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup/shutdown hooks."""
    setup_logging()
    logger.info("app_starting", env=get_settings().app_env)
    yield
    logger.info("app_shutting_down")


def create_app() -> FastAPI:
    """Application factory - creates and configures the FastAPI instance."""
    settings = get_settings()
    
    app = FastAPI(
        title="GovNotify India",
        description="Government notification aggregator and digest platform",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # --- CORS ---
    # Relaxed for Vercel deployment without custom domain
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Rate Limiting ---
    if not settings.is_testing:
        from govnotify.api.rate_limit import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)

    # --- Request-ID middleware ---
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()).replace("-", "")[:12])
        set_correlation_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # --- Exception handlers ---
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(status_code=429, headers={"Retry-After": "60"}, content={"detail": str(exc)})

    @app.exception_handler(GovNotifyError)
    async def domain_exception_handler(request: Request, exc: GovNotifyError):
        logger.warning("domain_error", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "govnotify"}

    # --- Register routers ---
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
    app.include_router(categories_router, prefix="/api/v1/categories", tags=["categories"])
    app.include_router(config_router, prefix="/api/v1/config", tags=["config"])
    app.include_router(notifications_router, prefix="/api/v1", tags=["notifications"])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])

    # --- Static files ---
    static_dir = "/app/static"
    if not os.path.exists(static_dir):
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        static_dir = os.path.join(base_path, "static")
    
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(os.path.join(static_dir, "index.html"))
    
    return app

app = create_app()
