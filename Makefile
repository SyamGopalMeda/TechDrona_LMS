# Tech Drona LMS — convenience targets (Linux/macOS/WSL/Git Bash with GNU make).
# Windows PowerShell users: use scripts/*.ps1 directly (see docs/local-development.md).
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TF_IMAGE    ?= hashicorp/terraform:1.9.8
API_DIR     := apps/api
WEB_DIR     := apps/web
VENV_BIN    := $(API_DIR)/.venv/bin

.PHONY: help up up-app down ps logs reset-db install-api migrate seed api web test test-api test-web \
        lint-infra tf-fmt actionlint

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

up: ## Start data services (postgres, redis x2, mailpit, s3) and wait for healthy
	scripts/dev-up.sh

up-app: ## Start data services + full app profile (api :18000, web :13000, workers, beat, judge, sealer)
	scripts/dev-up.sh --with-app --build

down: ## Stop containers (volumes kept)
	docker compose --profile app --profile errors-local down

ps: ## Container status
	docker compose ps -a

logs: ## Follow logs
	docker compose logs -f --tail=100

reset-db: ## DESTROY local Postgres volume, re-init, migrate
	scripts/reset-db.sh --force

install-api: ## Create apps/api/.venv and install with dev extras
	cd $(API_DIR) && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e ".[dev]"

migrate: ## alembic upgrade heads (techdrona)
	cd $(API_DIR) && .venv/bin/alembic upgrade heads

seed: ## Load DEV/DEMO data (rbac, users, catalog, placement, coding, commerce, security); refuses in prod
	scripts/seed-dev.sh

api: ## Run the API with reload on :8000
	cd $(API_DIR) && .venv/bin/uvicorn --factory app.main:create_app --reload --host 127.0.0.1 --port $${TD_API_PORT:-8000} --env-file ../../.env

web: ## Run the web app (next dev) on :3000
	cd $(WEB_DIR) && ( [ -d node_modules ] || npm ci ) && npm run dev

test-api: ## ruff, mypy, pytest + coverage (G-01, G-02)
	cd $(API_DIR) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy \
	  && .venv/bin/coverage run -m pytest && .venv/bin/coverage report --fail-under=$${COVERAGE_FAIL_UNDER:-85}

test-web: ## lint, typecheck, vitest, build
	cd $(WEB_DIR) && npm run lint && npm run typecheck \
	  && npm test && npm run build

test: test-api test-web ## All local gates

tf-fmt: ## terraform fmt (in a throwaway container; no local install needed)
	docker run --rm -v "$(CURDIR)/docs/archive/aws-terraform/terraform:/work" -w /work $(TF_IMAGE) fmt -recursive

lint-infra: ## terraform fmt -check + validate (dev env) in a throwaway container
	docker run --rm -v "$(CURDIR)/docs/archive/aws-terraform/terraform:/src:ro" --entrypoint sh $(TF_IMAGE) -c \
	  'cp -r /src /work && cd /work && terraform fmt -check -recursive && cd envs/dev && terraform init -backend=false -input=false >/dev/null && terraform validate'

actionlint: ## Lint GitHub workflows
	docker run --rm -v "$(CURDIR):/repo" -w /repo rhysd/actionlint:1.7.7
