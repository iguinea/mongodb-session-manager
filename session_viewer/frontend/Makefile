.PHONY: run open clean help

# Default target
.DEFAULT_GOAL := help

# Frontend server
run: ## Start HTTP server on port 8883
	@echo "Starting frontend server on http://localhost:8883"
	@python3 -m http.server 8883

open: ## Open frontend in browser
	@echo "Opening http://localhost:8883 in browser..."
	@open http://localhost:8883 || xdg-open http://localhost:8883 || start http://localhost:8883

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
