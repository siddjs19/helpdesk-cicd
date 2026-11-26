# Campus IT Helpdesk — developer entry points.
#
#   make            list every target
#   make test       run the pytest suite
#   make docker-build / make docker-run / make smoke
#
# Recipes are indented with real TAB characters (required by make).

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
IMAGE  ?= campus-helpdesk:local
PORT   ?= 8000
BASE_URL ?= http://127.0.0.1:$(PORT)

.DEFAULT_GOAL := help
.PHONY: help venv install run test cov lint format check docker-build docker-run docker-stop compose-up compose-down smoke clean

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtual environment
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: venv ## Install runtime and development dependencies
	$(BIN)/pip install -r requirements-dev.txt

run: ## Run the development server on :8000
	FLASK_APP=wsgi:app $(BIN)/flask run --host 0.0.0.0 --port $(PORT)

test: ## Run the test suite
	$(BIN)/python -m pytest

cov: ## Run tests with coverage and fail under 85%
	$(BIN)/python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=85

lint: ## Lint with ruff
	$(BIN)/ruff check .

format: ## Auto-format with ruff
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

check: lint test ## Run everything CI runs before a push

docker-build: ## Build the container image
	docker build -t $(IMAGE) --build-arg GIT_SHA=$$(git rev-parse --short HEAD 2>/dev/null || echo local) .

docker-run: ## Run the container on :8000
	docker run --rm -d --name helpdesk -p $(PORT):8000 \
		-e SECRET_KEY=local-dev -e SESSION_COOKIE_SECURE=0 $(IMAGE)

docker-stop: ## Stop the container
	docker stop helpdesk || true

compose-up: ## Start the stack with docker compose
	docker compose up -d --build

compose-down: ## Stop the stack
	docker compose down -v

smoke: ## Run the post-deploy smoke test against $(BASE_URL)
	BASE_URL=$(BASE_URL) ./scripts/smoke_test.sh

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage coverage.xml reports
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
