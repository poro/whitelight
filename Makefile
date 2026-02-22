.PHONY: install dev test lint type-check fmt seed sync run dry-run clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/unit/ -v

test-all:
	pytest -v

test-cov:
	pytest tests/unit/ --cov=whitelight --cov-report=term-missing

lint:
	ruff check src/ tests/

type-check:
	mypy src/whitelight/

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

seed:
	python scripts/seed_cache.py

sync:
	python -m whitelight sync

run:
	python -m whitelight run

dry-run:
	python -m whitelight run --dry-run

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
