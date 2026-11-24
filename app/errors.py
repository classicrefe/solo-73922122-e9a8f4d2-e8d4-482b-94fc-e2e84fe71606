"""Domain errors mapped to HTTP responses by the FastAPI layer."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any | None = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            detail["details"] = self.details
        return detail


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class NoFeasibleInterpretation(AppError):
    status_code = 422
    code = "no_feasible_interpretation"


class ShipNotFound(AppError):
    status_code = 404
    code = "ship_not_found"


class ShipConflict(AppError):
    status_code = 409
    code = "ship_conflict"


class RevisionConflict(AppError):
    status_code = 409
    code = "revision_conflict"


class StorageUnavailable(AppError):
    status_code = 500
    code = "storage_error"
