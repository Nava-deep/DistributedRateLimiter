PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: install run lint test test-unit test-integration test-concurrency test-failure migrate seed-demo compose-up compose-down benchmark benchmark-report simulate-multi-region

install:
	$(PIP) install -e ".[dev]"

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint:
	ruff check .

test:
	pytest -q

test-unit:
	pytest -q -m unit

test-integration:
	pytest -q -m integration

test-concurrency:
	pytest -q -m concurrency

test-failure:
	pytest -q -m failure

migrate:
	alembic upgrade head

seed-demo:
	$(PYTHON) scripts/seed_demo_policies.py

compose-up:
	docker compose up --build

compose-down:
	docker compose down --remove-orphans

benchmark:
	$(PYTHON) scripts/run_benchmark.py

benchmark-report:
	$(PYTHON) scripts/run_benchmark.py --notes "Synthetic benchmark run"

simulate-multi-region:
	$(PYTHON) scripts/run_multi_region_simulation.py
