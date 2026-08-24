# Development

## Prerequisites

- Docker Desktop
- Python 3.11+ and Node 22+ if you want to run tests outside containers

## Running

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Backend hot-reloads from `backend/app`; the frontend runs Vite on port 5173 and
proxies `/api` to the backend, so the browser always sees a single origin.

## Tests

```bash
make test            # both suites
make test-backend    # pytest
make test-frontend   # vitest
```

Outside Docker:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest

cd frontend && npm install && npm run test
```

Unit tests never touch PostgreSQL, Redis, or Binance. Tests marked
`integration` need a reachable database and skip themselves when it is absent.
Automated tests never use real Binance credentials.

Test settings are built with `tests.conftest.make_settings()`, which ignores
`.env` and the ambient environment, so a developer's local configuration cannot
change test outcomes.

## Linting and types

```bash
make lint            # ruff + eslint + tsc --noEmit
```

## Migrations

The schema is never created implicitly at startup.

```bash
make migrate                                        # apply
docker compose run --rm migrate alembic downgrade -1
docker compose run --rm backend alembic revision --autogenerate -m "add x"
```

Alembic reads its database URL from application settings, so no credentials
live in `alembic.ini`.

## Conventions

- Type hints everywhere; Pydantic schemas at the API boundary.
- No business logic in `main.py`.
- No global mutable state beyond the explicitly initialised singletons
  (engine, Redis client, event bus, connection manager, health service), each
  with an `init_*` / `get_*` / `reset_*` trio so tests can control them.
- Anything not implemented is marked `NOT IMPLEMENTED` in code, docs, and UI —
  never covered up with placeholder output.
- Risk parameters are defined once, in `app/config/risk_config.py`.

## Adding a WebSocket event

1. Add the member to `EventType` in `backend/app/core/events.py`.
2. Add the same string to `EVENT_TYPES` in `frontend/src/types/events.ts`.
3. Document it in `docs/API.md`.
4. Publish it with `await get_event_bus().publish(Event.of(...))`.
