-include .env
export

# Use BRAND or brand if provided (e.g. make playground BRAND=goog), otherwise fallback to ACTIVE_BRAND from .env
BRAND_INPUT := $(if $(BRAND),$(BRAND),$(brand))
BRAND_ID := $(if $(BRAND_INPUT),$(shell echo "$(BRAND_INPUT)" | tr '[:upper:]' '[:lower:]' | tr ' ' '_'),$(ACTIVE_BRAND))

# Sync brand assets and update .env if needed
sync-assets: authenticate
	@if [ -z "$(BRAND_ID)" ]; then echo "❌ ERROR: BRAND is required (or set ACTIVE_BRAND in .env)"; exit 1; fi
	@if [ ! -d "app/brands/$(BRAND_ID)" ]; then echo "❌ ERROR: Brand folder 'app/brands/$(BRAND_ID)' not found."; exit 1; fi
	@# Update .env if a brand was explicitly provided
	@if [ ! -z "$(BRAND_INPUT)" ]; then \
		sed -i '' "s/^ACTIVE_BRAND=.*/ACTIVE_BRAND=$(BRAND_ID)/" .env 2>/dev/null || \
		sed -i "s/^ACTIVE_BRAND=.*/ACTIVE_BRAND=$(BRAND_ID)/" .env || \
		echo "ACTIVE_BRAND=$(BRAND_ID)" >> .env; \
		echo "✅ Persistent brand set to: $(BRAND_ID)"; \
	fi
	@echo "🔄 Syncing assets for brand: $(BRAND_ID)..."
	@if [ -d "app/brands/$(BRAND_ID)/assets" ]; then \
		gsutil -m rsync -r app/brands/$(BRAND_ID)/assets gs://$(GOOGLE_CLOUD_BUCKET_ARTIFACTS)/brands/$(BRAND_ID)/assets; \
	fi

# ==============================================================================
# Installation & Setup
# ==============================================================================

# Install dependencies using uv package manager
install:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Installing uv..."; curl -LsSf https://astral.sh/uv/0.8.13/install.sh | sh; source $HOME/.local/bin/env; }
	uv sync

# Authenticate with Google Cloud and verify project consistency
authenticate:
	@echo "==============================================================================="
	@echo "| 🔐 Authenticating with Google Cloud...                                      |"
	@echo "==============================================================================="
	gcloud auth login
	gcloud auth application-default login
	@AUTH_PROJECT=$$(gcloud config get-value project 2>/dev/null); \
	if [ "$$AUTH_PROJECT" != "$(GOOGLE_CLOUD_PROJECT)" ]; then \
		echo "🔄 Authenticated project ($$AUTH_PROJECT) does not match. Setting project to $(GOOGLE_CLOUD_PROJECT)..."; \
		gcloud config set project $(GOOGLE_CLOUD_PROJECT); \
	else \
		echo "✅ Authenticated project matches GOOGLE_CLOUD_PROJECT: $$AUTH_PROJECT"; \
	fi
	gcloud auth application-default set-quota-project $(GOOGLE_CLOUD_PROJECT)

# ==============================================================================
# Playground Targets
# ==============================================================================

# Launch local dev playground
# Usage: make playground [BRAND=bofa]
playground: sync-assets
	@echo "==============================================================================="
	@echo "| 🚀 Starting your agent playground...                                        |"
	@echo "|                                                                             |"
	@echo "| 🏷️  Active Brand: $(BRAND_ID)"
	@echo "| 💡 Try asking: Set up a marketing campaign for a new product.            |"
	@echo "|                                                                             |"
	@echo "| 🌐 Project ID: $(GOOGLE_CLOUD_PROJECT)"
	@echo "| 🪣 Artifacts Bucket: $(GOOGLE_CLOUD_BUCKET_ARTIFACTS)"
	@echo "==============================================================================="
	export ACTIVE_BRAND=$(BRAND_ID); uv run adk web . --port 8501 --reload_agents

# Alias for debugging
debug: playground

# Set up a new brand profile
# Usage: make setup-brand BRAND="Brand Name" [URL="https://brand.com"]
setup-brand: authenticate
	@if [ -z "$(BRAND)" ]; then echo "❌ ERROR: BRAND is required. Usage: make setup-brand BRAND=\"Brand Name\""; exit 1; fi
	uv run -m app.app_utils.onboard_brand --name "$(BRAND)" $(if $(URL),--url "$(URL)")
	@$(MAKE) sync-assets BRAND="$(BRAND)"

# Remove a brand profile
# Usage: make remove-brand BRAND="Brand Name"
remove-brand:
	@if [ -z "$(BRAND)" ]; then echo "❌ ERROR: BRAND is required. Usage: make remove-brand BRAND=\"Brand Name\""; exit 1; fi
	@BRAND_ID=$$(echo "$(BRAND)" | tr '[:upper:]' '[:lower:]' | tr ' ' '_'); \
	if [ -d "app/brands/$$BRAND_ID" ]; then \
		rm -rf "app/brands/$$BRAND_ID"; \
		echo "✅ Brand '$$BRAND_ID' removed successfully."; \
	else \
		echo "⚠️ Brand '$$BRAND_ID' not found."; \
	fi

# ==============================================================================
# Backend Deployment Targets
# ==============================================================================

# Deploy the agent remotely
# Usage: make deploy [BRAND=goog] [AGENT_IDENTITY=true] [SECRETS="KEY=SECRET_ID,..."]
deploy: sync-assets
	@echo "==============================================================================="
	@echo "| 🚢 Deploying agent for brand: $(BRAND_ID)...                         |"
	@echo "==============================================================================="
	# Export dependencies to requirements file using uv export.
	(uv export --no-hashes --no-header --no-dev --no-emit-project --no-annotate > app/app_utils/.requirements.txt 2>/dev/null || \
	uv export --no-hashes --no-header --no-dev --no-emit-project > app/app_utils/.requirements.txt) && \
	export ACTIVE_BRAND=$(BRAND_ID); uv run -m app.app_utils.deploy \
		--source-packages=./app \
		--entrypoint-module=app.agent_engine_app \
		--entrypoint-object=agent_engine \
		--requirements-file=app/app_utils/.requirements.txt \
		$(if $(AGENT_IDENTITY),--agent-identity) \
		$(if $(filter command line,$(origin SECRETS)),--set-secrets="$(SECRETS)")

# Alias for 'make deploy' for backward compatibility
backend: deploy

# ==============================================================================
# Testing & Code Quality
# ==============================================================================

# Run unit and integration tests
test:
	uv sync --dev
	uv run pytest tests/unit && uv run pytest tests/integration

# ==============================================================================
# Agent Evaluation
# ==============================================================================

# Run agent evaluation using ADK eval
# Usage: make eval [BRAND=goog] [EVALSET=tests/eval/evalsets/basic.evalset.json] [EVAL_CONFIG=tests/eval/eval_config.json]
eval: sync-assets
	@echo "==============================================================================="
	@echo "| 🧪 Running Agent Evaluation for brand: $(BRAND_ID)                      |"
	@echo "==============================================================================="
	uv sync --dev --extra eval
	export ACTIVE_BRAND=$(BRAND_ID); uv run adk eval ./app $(if $(EVALSET),$(EVALSET),tests/eval/evalsets/marketing.evalset.json) \
		$(if $(EVAL_CONFIG),--config_file_path=$(EVAL_CONFIG),$(if $(wildcard tests/eval/eval_config.json),--config_file_path=tests/eval/eval_config.json,))

# Run evaluation with all evalsets
eval-all:
	@echo "==============================================================================="
	@echo "| Running All Evalsets                                                        |"
	@echo "==============================================================================="
	@for evalset in tests/eval/evalsets/*.evalset.json; do \
		echo ""; \
		echo "▶ Running: $$evalset"; \
		$(MAKE) eval EVALSET=$$evalset || exit 1; \
	done
	@echo ""
	@echo "✅ All evalsets completed"

# Run code quality checks (codespell, ruff, ty)
lint:
	uv sync --dev --extra lint
	uv run codespell
	uv run ruff check . --diff
	uv run ruff format . --check --diff
	uv run ty check .

# ==============================================================================
# Gemini Enterprise Integration
# ==============================================================================

# Register the deployed agent to Gemini Enterprise
# Usage: make register-gemini-enterprise (interactive - will prompt for required details)
# For non-interactive use, set env vars: ID or GEMINI_ENTERPRISE_APP_ID (full GE resource name)
# Optional env vars: GEMINI_DISPLAY_NAME, GEMINI_DESCRIPTION, GEMINI_TOOL_DESCRIPTION, AGENT_ENGINE_ID
register-gemini-enterprise:
	uv pip install agent-starter-pack==0.41.3
	uv run --env-file .env agent-starter-pack register-gemini-enterprise