# Convenience targets.  Windows users: see scripts/*.ps1 for equivalents (§67).
.DEFAULT_GOAL := help
COMPOSE := docker compose
DEV := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: help up down dev logs migrate test test-backend test-frontend lint \
        build backup restore list-backups export import verify health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the full stack
	$(COMPOSE) up -d

down: ## Stop the stack (persistent data is untouched)
	$(COMPOSE) down

dev: ## Start the stack with hot reload
	$(DEV) up -d

logs: ## Follow backend logs
	$(COMPOSE) logs -f backend

migrate: ## Apply database migrations
	python scripts/manage.py migrate

health: ## Print the health endpoint
	curl -sS http://localhost:8000/api/v1/system/health

test: test-backend test-frontend ## Run all tests

test-backend: ## Run the backend test suite
	cd backend && python -m pytest

test-frontend: ## Run the frontend test suite
	cd frontend && npm run test

lint: ## Lint backend and frontend
	cd backend && python -m ruff check .
	cd frontend && npm run lint && npm run typecheck

build: ## Build all images
	$(COMPOSE) build

backup: ## Create a manual backup
	python scripts/manage.py backup

restore: ## Restore a backup:  make restore NAME=backup-...
	python scripts/manage.py restore --name $(NAME) --yes

list-backups: ## List available backups
	python scripts/manage.py list-backups

export: ## Bundle a backup:  make export NAME=backup-...
	python scripts/manage.py export --name $(NAME)

import: ## Import a bundle:  make import ARCHIVE=path/to/file.tar.gz
	python scripts/manage.py import $(ARCHIVE)

verify: ## Check the persistent directory layout
	python scripts/manage.py verify
