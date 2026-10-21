PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: setup test lint demo demo-cli probe run clean

setup:  ## Create the virtualenv and install CareLoop with dev tools (needs Python 3.11+)
	@$(PYTHON) -c "import sys; assert sys.version_info >= (3, 11), 'CareLoop needs Python 3.11+. Try: make setup PYTHON=python3.11'"
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Setup done. Edit .env, then run: make probe"

test:  ## Run the test suite
	$(BIN)/pytest -q

lint:  ## Lint with ruff
	$(BIN)/ruff check .

probe:  ## Call the real Ring API with RING_ACCESS_TOKEN and save scrubbed fixtures
	$(BIN)/python scripts/ring_probe.py

run:  ## Start CareLoop with the settings in .env
	$(BIN)/uvicorn app.main:create_app --factory --app-dir backend --port 8000

demo:  ## Start in demo mode, then open http://127.0.0.1:8000 and use the demo panel
	@echo "Open http://127.0.0.1:8000  (Ctrl+C to stop)"
	DEMO_MODE=true DATABASE_URL=sqlite:///careloop-demo.db $(BIN)/uvicorn app.main:create_app --factory --app-dir backend --port 8000

demo-cli:  ## Run one scenario in the terminal: make demo-cli SCENARIO=missed-morning
	DEMO_MODE=true DATABASE_URL=sqlite:///careloop-demo.db $(BIN)/python scripts/demo_scenario.py --scenario $(or $(SCENARIO),missed-morning)

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache *.db
