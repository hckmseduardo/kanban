"""Team Kanban API - FastAPI backend for individual team instances"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

from .routes import boards, columns, cards, members, webhooks, utils
from .services.database import Database

# Configuration
TEAM_SLUG = os.getenv("TEAM_SLUG", "default")
DOMAIN = os.getenv("DOMAIN", "localhost")
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))

db = Database(DATA_DIR / "db" / "team.json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    db.initialize()
    yield


app = FastAPI(
    title=f"Kanban API - {TEAM_SLUG}",
    description="Team Kanban board API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"https://{TEAM_SLUG}.{DOMAIN}",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes (no /api prefix - Traefik strips it before forwarding)
app.include_router(boards.router, prefix="/boards", tags=["boards"])
app.include_router(columns.router, prefix="/columns", tags=["columns"])
app.include_router(cards.router, prefix="/cards", tags=["cards"])
app.include_router(members.router, prefix="/members", tags=["members"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(utils.router, prefix="/utils", tags=["utils"])


@app.get("/health")
async def health():
    return {"status": "healthy", "team": TEAM_SLUG}


@app.get("/team")
async def get_team_info():
    return {"slug": TEAM_SLUG, "domain": f"{TEAM_SLUG}.{DOMAIN}"}
