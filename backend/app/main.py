from fastapi import FastAPI

from app.api.v1 import health, nodes


def create_app() -> FastAPI:
    app = FastAPI(title="Nodecraft", version="0.1.0")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(nodes.router, prefix="/api/v1")
    return app


app = create_app()
