from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.api.v1 import health, nodes, stored, workflows
from app.config import get_settings
from app.storage.db import make_engine, make_session_factory, upgrade_to_head


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or get_settings().effective_database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        upgrade_to_head(url)  # fail fast on a bad/unmigratable database
        engine = make_engine(url)
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Nodecraft", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(nodes.router, prefix="/api/v1")
    app.include_router(workflows.router, prefix="/api/v1")  # validate + ad-hoc run
    app.include_router(stored.router, prefix="/api/v1")
    return app


app = create_app()
