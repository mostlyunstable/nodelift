.PHONY: setup dev dev-api dev-web stop test lint check app install-app

setup:
	cd backend && uv sync
	cd apps/web && pnpm install

# One random API token per `make dev`, shared by the API and the Vite proxy (the browser never sees it).
dev:
	@NODECRAFT_API_TOKEN=$$(python3 -c "import secrets; print(secrets.token_urlsafe(32))") \
		$(MAKE) -j2 dev-api dev-web

# Set NODECRAFT_RELOAD=1 for auto-reload (its reloader child can outlive Ctrl+C; run `make stop` after).
dev-api:
	cd backend && uv run python -m app

dev-web:
	cd apps/web && pnpm dev

stop:
	-@for p in 8000 5173; do lsof -nP -tiTCP:$$p -sTCP:LISTEN | xargs kill 2>/dev/null; done; true

test:
	cd backend && uv run pytest
	cd apps/web && pnpm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd apps/web && pnpm typecheck

check: lint test

# Desktop app (macOS). Needs Rust: `brew install rustup && rustup default stable`.
app:
	scripts/build_app.sh

install-app:
	scripts/build_app.sh --install
