"""Kanban Portal API - Main Application"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes import auth, users, teams, tasks, portal_api, team_api
from app.services.redis_service import redis_service
from app.services.task_service import task_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting Kanban Portal API...")
    await redis_service.connect()
    logger.info(f"Connected to Redis at {settings.redis_url}")
    yield
    # Shutdown
    logger.info("Shutting down Kanban Portal API...")
    await redis_service.disconnect()


# Create FastAPI app
# root_path is set for OpenAPI URL generation when behind reverse proxy
# Traefik strips /api from incoming requests, but docs need to know the external path
app = FastAPI(
    title=settings.app_name,
    description="Central API for Kanban platform - user and team management",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path="/api",
    lifespan=lifespan
)

# CORS Configuration
# Allow portal frontends and any team subdomain
base_origins = [
    f"https://{settings.domain}",  # Main domain (production)
    f"https://{settings.domain}:{settings.port}",
    f"https://app.{settings.domain}",  # Legacy app subdomain
    f"https://app.{settings.domain}:{settings.port}",
    f"https://api.{settings.domain}",
    f"https://api.{settings.domain}:{settings.port}",
    "https://localhost",
    f"https://localhost:{settings.port}",
    "http://localhost:3000",  # Dev frontend
]


def is_allowed_origin(origin: str) -> bool:
    """Check if origin is allowed (base origins or team subdomain)"""
    if origin in base_origins:
        return True
    # Allow any subdomain of the configured domain
    # E.g., https://team-name.localhost:4443 or https://team-name.kanban.amazing-ai.tools
    import re
    if settings.port == 443:
        pattern = rf"^https://[a-z0-9-]+\.{re.escape(settings.domain)}$"
    else:
        pattern = rf"^https://[a-z0-9-]+\.{re.escape(settings.domain)}:{settings.port}$"
    return bool(re.match(pattern, origin))


class DynamicCORSMiddleware(CORSMiddleware):
    """CORS middleware that allows dynamic team subdomains"""

    async def is_allowed_origin(self, origin: str) -> bool:
        return is_allowed_origin(origin)


app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=base_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=rf"https://[a-z0-9-]+\.{settings.domain}(:{settings.port})?"
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(teams.router, prefix="/teams", tags=["Teams"])
app.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
app.include_router(portal_api.router, prefix="/portal", tags=["Portal API"])
app.include_router(team_api.router, prefix="/teams", tags=["Team API (Boards & Cards)"])


# Health check endpoints
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "portal-api",
        "version": "0.1.0"
    }


@app.get("/health/redis", tags=["Health"])
async def redis_health():
    """Redis health check"""
    is_connected = await redis_service.ping()
    return {
        "status": "healthy" if is_connected else "unhealthy",
        "service": "redis"
    }


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs"
    }
