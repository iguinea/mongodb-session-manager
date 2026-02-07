.PHONY: run open clean help

# Default target
.DEFAULT_GOAL := help

# Configurable port
PORT ?= 8883

# Frontend server
run: ## Start HTTP server on port 8883
	@echo "Starting frontend server on http://localhost:$(PORT)"
	@python3 -m http.server $(PORT)

open: ## Open frontend in browser
	@echo "Opening http://localhost:$(PORT) in browser..."
	@open http://localhost:$(PORT) || xdg-open http://localhost:$(PORT) || start http://localhost:$(PORT)

# Cleanup
clean: ## Clean up temporary files
	@echo "Cleaning up..."
	@find . -type f -name ".DS_Store" -delete
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Help
help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
