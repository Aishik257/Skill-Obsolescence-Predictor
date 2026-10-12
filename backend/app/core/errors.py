"""Application-level exceptions mapped to HTTP responses in main.py."""
from __future__ import annotations


class AppError(Exception):
    """Base error carrying an HTTP status and a human-readable message."""

    status_code = 500

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class BadRequestError(AppError):
    status_code = 400


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UnprocessableError(AppError):
    status_code = 422


class PipelineError(AppError):
    status_code = 500
