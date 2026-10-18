.PHONY: setup dev dev-api dev-web test lint check

setup:
	cd backend && uv sync
	cd apps/web && pnpm install

dev:
	$(MAKE) -j2 dev-api dev-web

dev-api:
	cd backend && uv run python -m app

dev-web:
	cd apps/web && pnpm dev

test:
	cd backend && uv run pytest
	cd apps/web && pnpm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd apps/web && pnpm typecheck

check: lint test
