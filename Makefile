.PHONY: dev down logs seed migrate test lint fmt fake-batch

dev:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python -m apps.api.seed

test:
	pytest

lint:
	ruff check .
	mypy apps packages

fmt:
	ruff format .
	ruff check --fix .

# Simulate a hub uploading a batch (requires `make seed` to have created
# the demo hub and its API token).
fake-batch:
	python scripts/fake_hub_post.py
