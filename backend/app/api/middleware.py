"""Request context middleware and exception handlers (§46, §100)."""

from __future__ import annotations

import time
from typing import ClassVar
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security response headers (§60, §99).

    The API is JSON-only and serves no HTML of its own, so the goal is
    narrow: make a browser refuse to reinterpret a response as something
    executable, and refuse to frame it. Deliberately *not* set here:

    * HSTS -- this is a local-first platform normally reached over plain
      HTTP on localhost; sending it would poison the browser's HSTS cache
      for that host and break the stack for the user.
    * A restrictive CSP on API responses -- the frontend is served
      separately by nginx, which is where a page CSP belongs.
    """

    HEADERS: ClassVar[dict[str, str]] = {
        # Never let a browser sniff a JSON error into HTML or a script.
        "X-Content-Type-Options": "nosniff",
        # No page here is ever meant to be framed (clickjacking).
        "X-Frame-Options": "DENY",
        # Don't leak API paths (which include ids) to third parties.
        "Referrer-Policy": "no-referrer",
        # This API needs none of these; deny them rather than inherit
        # whatever the browser's default happens to be.
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        for header, value in self.HEADERS.items():
            response.headers.setdefault(header, value)
        return response


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
