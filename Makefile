.PHONY: dev test lint check

dev:
	cd backend && uv run python -m app

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy

check: lint test
