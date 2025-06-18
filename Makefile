.PHONY: help install install-dev test test-cov lint format clean build upload docs serve-docs
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in development mode
	uv sync

install-dev: ## Install with development dependencies
	uv sync --dev

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage
	uv run pytest --cov=src/malla --cov-report=html --cov-report=term

lint: ## Run linting tools
	uv run ruff check src tests
	uv run basedpyright src

format: ## Format code
	uv run ruff format src tests
	uv run ruff check --fix src tests

clean: ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean ## Build the package
	uv build

upload: build ## Upload to PyPI (requires authentication)
	uv publish

docs: ## Build documentation
	@echo "Documentation build not yet configured"

serve-docs: ## Serve documentation locally
	@echo "Documentation serving not yet configured"

run-web: ## Run the web UI
	./malla-web

run-capture: ## Run the MQTT capture tool
	./malla-capture

dev-setup: install-dev ## Set up development environment
	uv run pre-commit install

check: lint test ## Run all checks (lint + test)

ci: install-dev check ## Run CI pipeline locally 