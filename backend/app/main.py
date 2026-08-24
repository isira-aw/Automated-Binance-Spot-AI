"""ASGI entrypoint.

Deliberately thin: all wiring lives in :mod:`app.api.app_factory` (§2).
"""

from __future__ import annotations

from app.api.app_factory import create_app

app = create_app()
