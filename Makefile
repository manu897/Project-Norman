.PHONY: dev down logs seed migrate test lint fmt fake-batch fake-publish

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

# Simulate a hub uploading a batch via the HTTPS path (requires `make seed`).
fake-batch:
	python scripts/fake_hub_post.py

# Simulate a hub publishing via the MQTT path — what Carl actually does.
# Topic: carl/{site_id}/{node_id}. Requires mosquitto from `make dev` running.
fake-publish:
	python scripts/fake_hub_publish.py
