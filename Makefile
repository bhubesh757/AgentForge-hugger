# AgentForge AI — developer entrypoints. Run `make help`.
SHELL := /bin/bash
COMPOSE     := docker compose
CORE        := $(COMPOSE) -f docker-compose.yml
FULL        := $(COMPOSE) -f docker-compose.yml -f docker-compose.kafka.yml --profile kafka --profile workers
MONITORING  := $(COMPOSE) -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring
ALL         := $(COMPOSE) -f docker-compose.yml -f docker-compose.kafka.yml -f docker-compose.monitoring.yml --profile kafka --profile workers --profile monitoring
SANDBOX_TAG ?= agentforge-sandbox:1.0.1

.DEFAULT_GOAL := help
.PHONY: help env gen-keys up up-full up-monitoring up-all down down-volumes logs ps migrate \
        test-backend test-frontend lint build-images build-sandbox config

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

env: ## Create .env from .env.example (only if missing) and generate keys
	@if [ ! -f .env ]; then cp .env.example .env; python3 infrastructure/scripts/gen-keys.py .env; else echo ".env exists (unchanged)"; fi

gen-keys: ## (Re)generate JWT_SECRET + Fernet CREDENTIAL_ENCRYPTION_KEY in .env (prints them if no .env)
	@python3 infrastructure/scripts/gen-keys.py .env

up: env ## Core stack: postgres, redis, migrate, backend, frontend (inline dispatch)
	$(CORE) up -d --build

up-full: env build-sandbox ## Core + Kafka + workers (kafka dispatch)
	$(FULL) up -d --build

up-monitoring: env ## Core + Prometheus/Grafana/Loki
	$(MONITORING) up -d --build

up-all: env build-sandbox ## Everything (core + kafka + workers + monitoring)
	$(ALL) up -d --build

down: ## Stop all services (volumes kept)
	$(ALL) down --remove-orphans

down-volumes: ## Stop all services AND delete their data volumes
	$(ALL) down --volumes --remove-orphans

logs: ## Follow logs (SERVICE=backend to filter)
	$(ALL) logs -f --tail=200 $(SERVICE)

ps: ## Service status
	$(ALL) ps

migrate: ## Run alembic upgrade head (one-shot migrate service)
	$(CORE) run --rm migrate

test-backend: ## Backend tests via uv (needs postgres+redis reachable, see LOCAL_SETUP.md)
	cd backend && LLM_MOCK_MODE=true EXECUTION_DISPATCH=inline uv run pytest -q

test-frontend: ## Frontend unit tests
	cd frontend && pnpm test

lint: ## Lint backend (ruff) and frontend (eslint + typecheck)
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint && pnpm typecheck

build-sandbox: ## Build the sandbox image launched by tool-worker
	@if [ -f sandbox/Dockerfile ]; then docker build -t $(SANDBOX_TAG) sandbox; else echo "sandbox/Dockerfile missing - skipping"; fi

build-images: build-sandbox ## Build frontend, backend and worker images
	docker build -t agentforge/agentforge-ai-frontend:local frontend
	docker build -f backend/Dockerfile -t agentforge/agentforge-ai-backend:local .
	docker build -f workers/Dockerfile -t agentforge/agentforge-ai-worker:local .

config: ## Validate every compose combination
	$(CORE) config -q
	$(FULL) config -q
	$(MONITORING) config -q
	$(ALL) config -q
	@echo "compose config OK"
