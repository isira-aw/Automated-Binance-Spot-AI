"""FastAPI application factory.

Business logic never lives in ``main.py`` (§2); this module wires the app
together and ``main.py`` only exposes the resulting instance.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RequestContextMiddleware, register_exception_handlers
from app.api.v1.router import api_router
from app.api.v1.websocket import router as websocket_router
from app.config import Settings, get_settings
from app.core.logging_config import configure_logging
from app.lifespan import lifespan

DESCRIPTION = """
Local-first automated **Binance Spot** research and trading platform.

Prediction accuracy is never guaranteed. This system is built around
statistical validation, realistic backtesting, risk management and continuous
model evaluation — not around promised returns.

Endpoints whose engines are not built yet return HTTP 501 with
`code: "NOT_IMPLEMENTED"` instead of placeholder data.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, log_dir=settings.paths.logs)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings

    # Explicit allow-list; never "*" in production (§99).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(websocket_router, prefix=settings.api_v1_prefix)

    return app
