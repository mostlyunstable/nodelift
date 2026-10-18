from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.api.v1 import health, nodes, stored, workflows
from app.config import Settings, get_settings
from app.nodes import default_registry, load_plugins
from app.runtime.subprocess_runner import SubprocessRunner
from app.services.run_hub import RunHub
from app.storage.db import make_engine, make_session_factory, upgrade_to_head
from app.storage.repositories import SqlRunRepository


def create_app(database_url: str | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    url = database_url or settings.effective_database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        upgrade_to_head(url)  # fail fast on a bad/unmigratable database
        engine = make_engine(url)
        app.state.session_factory = make_session_factory(engine)
        app.state.settings = settings
        app.state.runner = SubprocessRunner(settings.node_memory_mb, settings.node_max_file_mb)
        registry = default_registry(app.state.runner, settings.http_allow_private)
        load_plugins(registry, settings.plugin_modules)
        app.state.registry = registry
        app.state.run_hub = RunHub()
        runs = SqlRunRepository(app.state.session_factory)
        for run_id in runs.mark_stale_running():  # runs orphaned by a crash or restart
            runs.add_event(
                run_id, "run.finished", {"status": "failed", "reason": "server_restarted"}
            )
        yield
        for task in list(app.state.run_hub.tasks):
            task.cancel()
        engine.dispose()

    app = FastAPI(title="Nodecraft", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(nodes.router, prefix="/api/v1")
    app.include_router(workflows.router, prefix="/api/v1")  # validate + ad-hoc run
    app.include_router(stored.router, prefix="/api/v1")
    return app


app = create_app()
