from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.security import SecurityMiddleware
from app.api.v1 import credentials, explorer, health, nodes, portability, stored, system, workflows
from app.config import Settings, get_settings
from app.nodes import default_registry, load_plugins
from app.runtime.subprocess_runner import SubprocessRunner
from app.services.explorer_service import ImportJobs
from app.services.gate import ExecutionGate
from app.services.run_hub import RunHub
from app.storage.db import make_engine, make_session_factory, upgrade_with_backup
from app.storage.repositories import SqlRepoRepository, SqlRunRepository
from app.storage.secret_stores import make_secret_store


def create_app(database_url: str | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    url = database_url or settings.effective_database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # fail fast on a bad/unmigratable database; an existing one is backed up first
        upgrade_with_backup(url, settings.effective_backup_dir, settings.keep_backups)
        engine = make_engine(url)
        app.state.session_factory = make_session_factory(engine)
        app.state.settings = settings
        app.state.database_url = url
        app.state.runner = SubprocessRunner(
            settings.node_memory_mb, settings.node_max_file_mb, settings.sandbox
        )
        registry = default_registry(app.state.runner, settings.http_allow_private)
        load_plugins(registry, settings.plugin_modules)
        app.state.registry = registry
        app.state.secrets = make_secret_store(settings)
        app.state.run_hub = RunHub()
        app.state.gate = ExecutionGate(
            settings.max_concurrent_runs, settings.max_concurrent_node_tests
        )
        runs = SqlRunRepository(app.state.session_factory)
        for run_id in runs.mark_stale_running():  # runs orphaned by a crash or restart
            runs.add_event(
                run_id, "run.finished", {"status": "failed", "reason": "server_restarted"}
            )
        app.state.import_jobs = ImportJobs()
        SqlRepoRepository(app.state.session_factory).fail_stale_imports()
        yield
        await app.state.import_jobs.shutdown()
        for task in list(app.state.run_hub.tasks):
            task.cancel()
        engine.dispose()

    app = FastAPI(title="Nodecraft", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(
        SecurityMiddleware,
        hosts=settings.host_list,
        origins=settings.origin_list,
        token=settings.api_token,
    )
    # Outermost, so a browser's credential-less CORS preflight is answered before the token check.
    # Only the configured origins (the desktop webview, the dev server) are ever allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Last-Event-ID"],
        expose_headers=["X-Has-More", "X-Next-After"],
        max_age=600,
    )
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(nodes.router, prefix="/api/v1")
    app.include_router(workflows.router, prefix="/api/v1")  # validate
    app.include_router(portability.router, prefix="/api/v1")  # before stored: /workflows/import
    app.include_router(stored.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(credentials.router, prefix="/api/v1")
    app.include_router(explorer.router, prefix="/api/v1")
    return app


app = create_app()
