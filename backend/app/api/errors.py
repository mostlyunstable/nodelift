from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: list[Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
