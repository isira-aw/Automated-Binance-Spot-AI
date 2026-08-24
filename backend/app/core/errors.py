"""Application error types and the single API error envelope (§100)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    metadata: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Every error the API returns uses this shape."""

    error: ErrorDetail


class AppError(Exception):
    """Base class for errors that map cleanly onto :class:`ErrorResponse`."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.metadata = metadata

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(
            error=ErrorDetail(
                code=self.code, message=self.message, metadata=self.metadata
            )
        )


class ConfigurationError(AppError):
    code = "CONFIGURATION_ERROR"
    status_code = 500


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class ServiceUnavailableError(AppError):
    code = "SERVICE_UNAVAILABLE"
    status_code = 503


class RiskLimitExceeded(AppError):
    code = "RISK_LIMIT_EXCEEDED"
    status_code = 409


class TradingDisabledError(AppError):
    code = "TRADING_DISABLED"
    status_code = 409


class NotImplementedYetError(AppError):
    """Explicitly marks functionality that is not built yet (§96).

    The system never fakes a feature.  Endpoints for phases that have not been
    implemented return this, so the UI can show `NOT IMPLEMENTED` rather than
    a plausible-looking placeholder.
    """

    code = "NOT_IMPLEMENTED"
    status_code = 501
