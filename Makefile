.PHONY: dev down logs seed migrate test lint fmt fake-publish

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

fake-publish:
	python scripts/fake_publisher.py --hub hub-001 --sensor node-3
