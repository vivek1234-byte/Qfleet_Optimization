"""
Typed application errors and their HTTP representation.

Routers raise these instead of building HTTPException by hand, so every error
response in the API has the same shape:

    {"error": {"code": "MODEL_NOT_TRAINED", "message": "...", "details": {...}}}
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class AppError(Exception):
    """Base class for all deliberate, client-facing failures."""

    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class ModelNotTrainedError(AppError):
    status_code = 409
    code = "MODEL_NOT_TRAINED"


class UnsupportedError(AppError):
    status_code = 400
    code = "UNSUPPORTED"


class ComputationError(AppError):
    status_code = 500
    code = "COMPUTATION_FAILED"
