"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from cheshire import __version__
from cheshire.api import (
    auth_routes,
    catalog_routes,
    consult_routes,
    discussion_routes,
    engine_routes,
    maintenance_routes,
    stream_routes,
)
from cheshire.providers import build_client
from cheshire.providers.base import LLMClient
from cheshire.settings import Settings


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    """`llm` overrides the configured provider (tests, offline use)."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool: ConnectionPool[psycopg.Connection[Any]] = ConnectionPool(
            settings.database_url, min_size=1, max_size=10, open=False
        )
        pool.open(wait=False)  # the API starts even if the database is still coming up
        app.state.pool = pool
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(title="Cheshire", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.llm_factory = (lambda: llm) if llm is not None else (lambda: build_client(settings))
    app.include_router(auth_routes.router)
    app.include_router(maintenance_routes.router)  # before catalog_routes: fixed paths first
    app.include_router(maintenance_routes.interview_router)
    app.include_router(discussion_routes.router)  # /decisions before catalog_routes' {kind}
    app.include_router(catalog_routes.router)
    app.include_router(engine_routes.router)
    app.include_router(stream_routes.router)  # before consult_routes: fixed paths first
    app.include_router(consult_routes.router)
    app.include_router(consult_routes.prefs_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
