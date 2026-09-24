.PHONY: setup serve demo test viewer
setup:
	uv sync --locked
	cd web && npm ci && npm run build
serve:
	uv run python -m cad.cli serve
demo:
	uv run python -m cad.cli demo
test:
	uv run ruff check cad tests
	uv run ruff format --check cad tests
	uv run pytest -q
	node --test scripts/cad-presentation.test.mjs
	cd web && npm run build
viewer:
	cd web && npm run dev
