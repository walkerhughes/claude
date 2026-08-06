.PHONY: lint lint-fix format typecheck check test test-unit test-integration coverage \
        validate-tasks evals mock-api benchmark-build benchmark benchmark-view

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

typecheck:
	uv run mypy src/

check: lint typecheck test-unit

test:
	uv run pytest

test-unit:
	uv run pytest -m unit

test-integration:
	uv run pytest -m integration

coverage:
	uv run pytest --cov --cov-report=term-missing

# Check every eval task verifier against its oracle and against each bypass route. No
# model and no API key, so it runs in CI. Needs Docker: rewardkit scores these checks
# and does not build on macOS.
validate-tasks:
	uv run python evals/generate_tasks.py
	bash evals/validate_local.sh
	python3 evals/check_reward.py --selftest

# THE MERGE GATE: drives the tasks with a real agent. Spends model tokens, needs Docker
# and CLAUDE_CODE_OAUTH_TOKEN. validate-tasks proves the verifiers work; only this
# proves an agent can actually drive the server.
evals:
	bash evals/run_gate.sh

# Run the mock FRED API on its own, the way the eval benchmark runs it.
mock-api:
	uv run python -m tests.fixtures.fred_api 8080

# Benchmark targets (need Docker running and CLAUDE_CODE_OAUTH_TOKEN set). These cd into
# evals/ so Harbor resolves the task path correctly regardless of where you invoke make,
# and call Harbor through uv so it does not need to be on PATH. Pinned to the version
# the tasks were validated against.
HARBOR ?= uv tool run --from "harbor==0.18.0" harbor

# Context is the plugin root so the image can copy the working tree it is testing.
benchmark-build:
	docker build -f evals/environment/Dockerfile -t fred-bench .

benchmark:
	cd evals && $(HARBOR) run -c job.yaml

benchmark-view:
	cd evals && $(HARBOR) view jobs
