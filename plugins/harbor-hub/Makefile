.PHONY: test test-integration test-e2e evals eval-safety validate-process lint format

test:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration -m integration

test-e2e:
	uv run pytest tests/e2e -m e2e

evals:
	./evals/run_evals.sh

eval-safety:
	./evals/run_eval_safety.sh

# Scores the process criteria against synthetic bypass and delegation runs.
# No hub, no Docker, no model -- unlike eval-safety, which needs all three.
validate-process:
	python3 ./evals/validate_process_local.py

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format .
