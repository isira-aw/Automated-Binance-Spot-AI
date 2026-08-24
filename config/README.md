# config/

Strategy and risk configuration files that live outside the container image and
are included in every backup.

This directory is intentionally empty at Phase 1: risk parameters currently come
from `backend/app/config/risk_config.py` and environment variables, which is the
single source of truth. Persisted, user-editable strategy profiles land here
when the configuration write API is built alongside the trading engine.

Secrets never belong here — they live in `.env`, which is gitignored.
