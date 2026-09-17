.PHONY: install build check test

install:
	npm install
	uv sync --project engine

build:
	npm run build

check:
	npm run protocol:check
	npm run check
	uv run --project engine ruff check engine scripts
	uv run --project engine ruff format --check engine scripts
	uv run --project engine mypy engine/src

test:
	npm test
	uv run --project engine pytest
