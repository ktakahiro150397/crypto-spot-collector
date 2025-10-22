.PHONY: help install test lint format type-check clean dev

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	uv sync --dev

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage
	uv run pytest --cov=src --cov-report=html --cov-report=term

lint: ## Run linter
	uv run flake8 src tests

format: ## Format code
	uv run black src tests
	uv run isort src tests

type-check: ## Run type checker
	uv run mypy src

clean: ## Clean up cache files
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage

dev: install ## Setup development environment
	uv run pre-commit install
	@echo "✅ Development environment is ready!"

check: format lint type-check test ## Run all checks

# Database commands
db-test: ## Test database connection
	uv run python test_db.py

db-shell: ## Connect to MySQL shell
	mysql -h mysql -u crypto_user -pcrypto_pass crypto_pachinko

db-logs: ## Show MySQL logs (only in devcontainer)
	docker logs crypto-spot-collector-mysql-1

db-reset: ## Reset database (WARNING: This will delete all data)
	mysql -h mysql -u root -prootpassword -e "DROP DATABASE IF EXISTS crypto_pachinko; CREATE DATABASE crypto_pachinko;"
	mysql -h mysql -u root -prootpassword -e "GRANT ALL PRIVILEGES ON crypto_pachinko.* TO 'crypto_user'@'%';"