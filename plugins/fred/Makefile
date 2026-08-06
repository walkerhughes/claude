.PHONY: lint lint-fix format typecheck check test test-unit test-integration coverage

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
