from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import AppError

__all__ = ["AppError", "install_error_handlers"]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
