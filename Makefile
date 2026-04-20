.PHONY: install lint format typecheck test ci clean

install:
	pip install -e ".[dev]"

lint:
	python -m ruff check src tests

format:
	python -m ruff format src tests

typecheck:
	python -m mypy src/unitygraph

test:
	python -m pytest

ci: lint typecheck test
	@echo "==> CI OK"

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
