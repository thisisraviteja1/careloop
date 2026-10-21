PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: setup test lint demo probe run clean

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

run:  ## Start the API server
	$(BIN)/uvicorn app.main:app --reload --app-dir backend

demo:  ## Full demo (arrives in Phase 5)
	@echo "The demo runner arrives in Phase 5. For now: make run, then open http://127.0.0.1:8000/healthz"

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache *.db
