.PHONY: install build check test

install:
	npm install
	uv sync --project engine

build:
	npm run build

check:
	npm run check
	uv run --project engine ruff check engine
	uv run --project engine mypy engine/src

test:
	npm test
	uv run --project engine pytest
