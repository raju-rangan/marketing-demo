-include .env
export

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
		echo "❌ ERROR: Authenticated project ($$AUTH_PROJECT) does not match GOOGLE_CLOUD_PROJECT ($(GOOGLE_CLOUD_PROJECT)) in .env"; \
		exit 1; \
	fi; \
	echo "✅ Authenticated project matches GOOGLE_CLOUD_PROJECT: $$AUTH_PROJECT"
	gcloud auth application-default set-quota-project $(GOOGLE_CLOUD_PROJECT)

# ==============================================================================
# Playground Targets
# ==============================================================================

# Launch local dev playground
playground: authenticate
	@echo "==============================================================================="
	@echo "| 🚀 Starting your agent playground...                                        |"
	@echo "|                                                                             |"
	@echo "| 💡 Try asking: Set up a marketing campaign for a new financial product.   |"
	@echo "|                                                                             |"
	@echo "| 🌐 Project ID: $(GOOGLE_CLOUD_PROJECT)"
	@echo "| 🪣 Artifacts Bucket: $(GOOGLE_CLOUD_BUCKET_ARTIFACTS)"
	@echo "|                                                                             |"
	@echo "| 🔍 IMPORTANT: Select the 'app' folder (JPMC Marketing Agent) to interact with your agent. |"
	@echo "==============================================================================="
	uv run adk web . --port 8501 --reload_agents

# ==============================================================================
# Backend Deployment Targets
# ==============================================================================

# Deploy the agent remotely
# Usage: make deploy [AGENT_IDENTITY=true] [SECRETS="KEY=SECRET_ID,..."] - Set AGENT_IDENTITY=true to enable per-agent IAM identity (Preview)
deploy: authenticate
	# Export dependencies to requirements file using uv export.
	(uv export --no-hashes --no-header --no-dev --no-emit-project --no-annotate > app/app_utils/.requirements.txt 2>/dev/null || \
	uv export --no-hashes --no-header --no-dev --no-emit-project > app/app_utils/.requirements.txt) && \
	uv run -m app.app_utils.deploy \
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
# Usage: make eval [EVALSET=tests/eval/evalsets/basic.evalset.json] [EVAL_CONFIG=tests/eval/eval_config.json]
eval:
	@echo "==============================================================================="
	@echo "| Running Agent Evaluation                                                    |"
	@echo "==============================================================================="
	uv sync --dev --extra eval
	uv run adk eval ./app $${tests/eval/evalsets/marketing.evalset.json} \
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