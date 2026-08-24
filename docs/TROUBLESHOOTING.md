# Troubleshooting

## The stack starts but the frontend shows "Backend unreachable"

Check the backend directly:

```bash
curl http://localhost:8000/api/v1/system/ping
docker compose logs backend --tail 100
```

## `/system/health` returns 503

The response body names the failing component. Common cases:

| Component | Meaning | Fix |
| --- | --- | --- |
| `database: DEGRADED` | Connected, no migrations applied | `make migrate` |
| `database: ERROR` | Cannot connect | Check `docker compose ps postgres` and `.env` credentials |
| `redis: ERROR` | Cannot connect | `docker compose ps redis` |
| `model_registry: ERROR` | A PRODUCTION model artifact is missing or corrupted | See MIGRATION.md — restore `models/`, or promote a different version |

Components reported as `NOT_IMPLEMENTED` or `DISABLED` do not make the system
unhealthy; they are phases that are not built, or Tier 2 features that are off.

## An endpoint returns 501 `NOT_IMPLEMENTED`

That endpoint's engine has not been built yet. The response's `metadata` names
the tier and the planned phase. This is deliberate: the platform never returns
placeholder data in place of a real feature.

## The backend refuses to start

Startup validates configuration first. Two blocking cases:

- `TRADING_MODE=LIVE` while `LIVE_TRADING_ENABLED=false` — this is intentional;
  live trading requires the explicit flag *and* an arm action.
- `CORS_ALLOW_ORIGINS=*` with `APP_ENV=production` — set an explicit
  allow-list.

## `docker compose down` and my data

`down` never deletes the database, models, artifacts, logs or backups: they are
bind mounts under the project directory, not Docker volumes. `down -v` also
leaves them alone for the same reason.

## Ports already in use

The compose file binds to `127.0.0.1` on 3000 (frontend), 8000 (backend), 5432
(PostgreSQL) and 6379 (Redis). Change the host side of the mapping in
`docker-compose.yml` if something else already owns one.

## Tests fail only on my machine

Backend tests ignore `.env` and scrub trading-related environment variables, so
a stale export is unlikely to be the cause. Integration tests marked
`integration` skip themselves when PostgreSQL is unreachable — a `s` in the
pytest output is expected on a bare checkout.
