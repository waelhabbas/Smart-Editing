"""FastAPI application factory for Smart Editing."""

import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from backend.config import FRONTEND_DIR
from backend.routers import explainer, templates, downloads

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Editing", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(explainer.router, prefix="/api/explainer", tags=["explainer"])
    app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
    app.include_router(downloads.router, prefix="/api", tags=["downloads"])

    # Serve frontend static files (must be last - catch-all)
    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
