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
from govnotify.storage.redis_store import RedisStore
from govnotify.logging_config import set_correlation_id, setup_logging
from govnotify.exceptions import GovNotifyError, RateLimitExceeded

# Route imports
from govnotify.api.v1.categories import router as categories_router
from govnotify.api.v1.config import router as config_router
from govnotify.api.v1.analytics import router as analytics_router
from govnotify.api.v1.feed import router as feed_router

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
        title="AIPulse",
        description="General news and government notification aggregator platform",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # --- Request-ID middleware ---
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()).replace("-", "")[:12])
        set_correlation_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # --- Rate Limiting Middleware ---
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # Only rate limit API calls in production, skip for OPTIONS (CORS preflight)
        if (settings.is_production and 
            request.url.path.startswith("/api/v1") and 
            request.method != "OPTIONS"):
            
            client_ip = request.client.host if request.client else "unknown"
            redis = RedisStore()
            # 60 requests per minute per IP
            is_allowed = await redis.check_rate_limit(
                user_id=f"ip:{client_ip}", 
                max_requests=60, 
                window_seconds=60
            )
            if not is_allowed:
                return JSONResponse(
                    status_code=429, 
                    headers={"Retry-After": "60"}, 
                    content={"detail": "Too many requests. Please try again in a minute."}
                )
        
        return await call_next(request)

    # --- CORS ---
    # Hardened for production: Only allow known origins
    # Added last to be the outermost middleware (ensures CORS headers even on 429/500 errors)
    allowed_origins = [
        "https://aipulse-daily.vercel.app",
        "http://localhost:8080",
        "http://localhost:3000",
        "capacitor://localhost",
        "http://localhost",
    ]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins if settings.is_production else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(feed_router, prefix="/api/v1/feed", tags=["feed"])
    app.include_router(categories_router, prefix="/api/v1/categories", tags=["categories"])
    app.include_router(config_router, prefix="/api/v1/config", tags=["config"])
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
