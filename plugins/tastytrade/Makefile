.PHONY: lint lint-fix format typecheck check selftest test test-unit test-integration coverage install-hooks validate-tasks mock-api benchmark-build benchmark benchmark-view

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

typecheck:
	uv run mypy src/

check: lint typecheck selftest test-unit

# Skill scripts are shipped payload but live outside src/, so pytest never sees
# them. Each carries its own assertions; this is what runs them.
selftest:
	python3 scripts/calendars.py --selftest

test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-integration:
	uv run pytest -m integration

coverage:
	uv run pytest --cov --cov-report=term-missing

install-hooks:
	git config core.hooksPath .githooks

# Check every eval task verifier against its oracle. No API key, so it runs in CI.
validate-tasks:
	uv run python evals/generate_tasks.py
	bash evals/validate_local.sh

# Run the mock Tastytrade API on its own, the way the eval benchmark runs it.
mock-api:
	uv run uvicorn tests.fixtures.mock_api.app:app --host 0.0.0.0 --port 8080

# Benchmark targets (need Docker running and ANTHROPIC_API_KEY set). These cd into evals/ so
# Harbor resolves the task path correctly regardless of where you invoke make, and call Harbor
# through uv so it does not need to be on PATH. The version is pinned to the one the tasks were
# validated against. Override with e.g. HARBOR=harbor to use a different harbor.
HARBOR ?= uv tool run --from "harbor==0.13.2" harbor

# Context is the plugin root so the image can copy the working tree it is testing.
benchmark-build:
	docker build -f evals/environment/Dockerfile -t tastytrade-bench .

benchmark:
	cd evals && $(HARBOR) run -c job.yaml

benchmark-view:
	cd evals && $(HARBOR) view jobs
