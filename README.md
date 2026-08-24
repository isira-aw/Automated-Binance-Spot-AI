# Automated Binance Spot AI

A local-first research and automated trading platform for **Binance Spot**
(BTC/USDT, ETH/USDT, BNB/USDT). Spot only — no futures, no margin, no leverage,
no short selling, and no withdrawal capability anywhere in the system.

> **This is not a guaranteed-profit machine.** Prediction accuracy is never
> guaranteed. The platform is built around statistical validation, realistic
> backtesting, risk control, uncertainty, and continuous model evaluation.
> Operating sequence is always **BACKTEST → PAPER → (optional, explicitly
> armed) LIVE**. Live trading is disabled by default.

## Current status

Phase 1 of the Tier 1 (MVP) track is implemented: project structure, Docker
stack, configuration system, persistent storage, PostgreSQL schema and
migrations, the FastAPI application, WebSocket infrastructure, and the React
frontend shell with live REST + WebSocket integration.

**No trading logic exists yet.** No market data is ingested, no signals are
produced, and no orders — paper or otherwise — are placed. Pages and API
namespaces whose engines are not built return an explicit `NOT_IMPLEMENTED`
rather than placeholder data. See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for
exactly what is and is not built.

## Quick start

```bash
cp .env.example .env      # then edit; .env is gitignored
docker compose up -d
```

| Service  | URL                                        |
| -------- | ------------------------------------------ |
| Frontend | http://localhost:3000                      |
| Backend  | http://localhost:8000                      |
| API docs | http://localhost:8000/docs                 |
| Health   | http://localhost:8000/api/v1/system/health |

Development mode (backend hot reload + Vite dev server on port 5173):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Windows equivalents live in `scripts/*.ps1` (`up.ps1`, `dev.ps1`, `migrate.ps1`,
`backup.ps1`, `restore.ps1`, `test.ps1`).

## Persistent storage

Containers are disposable; data is not. `docker compose down` never destroys:

```
data/       PostgreSQL cluster, market data, news, Redis persistence
models/     trained model artifacts (production / candidates / archive)
artifacts/  backtest results, reports, metrics
logs/       rotated structured logs
backups/    manual backups
config/     strategy and risk configuration files
```

## Documentation

| Document                                       | Contents                                  |
| ---------------------------------------------- | ----------------------------------------- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md)         | Module layout and data flow               |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md)           | Local setup, tests, conventions           |
| [API.md](docs/API.md)                           | REST endpoints and WebSocket events       |
| [TRADING_MODES.md](docs/TRADING_MODES.md)       | Backtest / paper / testnet / live         |
| [RISK_ENGINE.md](docs/RISK_ENGINE.md)           | Risk parameters and authority model       |
| [BINANCE_SETUP.md](docs/BINANCE_SETUP.md)       | API keys, permissions, security           |
| [MIGRATION.md](docs/MIGRATION.md)               | Backup, restore, moving to a new laptop   |
| [BACKTESTING.md](docs/BACKTESTING.md)           | Backtest design and bias audit            |
| [MODEL_TRAINING.md](docs/MODEL_TRAINING.md)     | Training pipeline and model registry      |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)   | Common problems                           |
| [PROJECT_STATUS.md](PROJECT_STATUS.md)          | Built / in progress / blocked / next      |

## Requirements

- Docker Desktop (Windows, macOS or Linux)
- CPU only — no GPU is required anywhere in this system

## Safety properties

- `LIVE_TRADING_ENABLED=false` by default; LIVE additionally requires an
  explicit arm action and is never restored implicitly after a restart.
- The risk engine is the highest-authority component. No model, no LLM and no
  frontend request may bypass it.
- Binance API keys never reach the browser and never enter the repository.
  Withdrawal permission is never required and no withdrawal function exists.
- Stale market data and unhealthy models can never trigger trades.
