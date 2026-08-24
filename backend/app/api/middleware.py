"""Request context middleware and exception handlers (§46, §100)."""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.errors import AppError, ErrorDetail, ErrorResponse
from app.core.logging_config import get_logger, request_id_var

logger = get_logger("api.middleware")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every request and log its completion."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        logger.info(
            "request completed",
            extra={
                "event_type": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response


def _envelope(code: str, message: str, metadata: dict | None = None) -> ErrorResponse:
    return ErrorResponse(error=ErrorDetail(code=code, message=message, metadata=metadata))


def register_exception_handlers(app: FastAPI) -> None:
    """Every error response uses the §100 envelope."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=exc.to_response().model_dump()
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                "VALIDATION_ERROR",
                "Request validation failed.",
                {"errors": exc.errors()},
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 403: "FORBIDDEN"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            extra={"event_type": "unhandled_exception", "path": request.url.path},
            exc_info=exc,
        )
        # The message is deliberately generic: internal details stay in the logs.
        return JSONResponse(
            status_code=500,
            content=_envelope(
                "INTERNAL_ERROR", "An internal error occurred."
            ).model_dump(),
        )
