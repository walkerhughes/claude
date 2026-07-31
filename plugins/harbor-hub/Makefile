.PHONY: test test-integration test-e2e evals eval-safety lint

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

lint:
	uv run ruff check . && uv run ruff format --check .
