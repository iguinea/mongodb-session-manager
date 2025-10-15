.PHONY: run dev format test clean help

# Default target
.DEFAULT_GOAL := help

# Backend server
run: ## Start the backend server
	uv run python main.py

dev: ## Start backend in development mode with auto-reload
	uv run uvicorn main:app --reload --host 0.0.0.0 --port 8882 --log-level info

# Code quality
format: ## Format code with ruff
	uv run ruff format .
	uv run ruff check --fix .

# Testing
test: ## Run tests (placeholder for future)
	@echo "Tests not yet implemented"

# Cleanup
clean: ## Clean up temporary files
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

# Help
help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
