from typing import Any


class AppError(Exception):
    """A failure with an HTTP-shaped meaning. Raised by services, rendered by the API layer."""

    def __init__(
        self, status: int, code: str, message: str, details: list[Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []
