# Project-Norman

## Summary
Project Norman is named after scientist Norman Borlaug, who is the man behind the green revolution and father of green revolution.

The project is addressing the monitoring issue of the agricultural field using IOT based sensor. This project will investigate and address the issues whole as a system (From Sensor to data management and Machine learning models are used to predict the crop yield and health)

The project details are in [Confluence](https://arttme.atlassian.net/l/cp/kPyWw9M7) and managed using monday.com


## Author:

[Manideep Reddy Tamma](mailto:manideepreddytamma@gmail.com)

[LinkedIn](https://www.linkedin.com/in/manideep-reddy-tamma/)

---

## What's in this repo

Norman is the **data + intelligence** side of a three-repo system:

| Repo               | Role                                                          |
| ------------------ | ------------------------------------------------------------- |
| `Project-Carl`     | Zephyr firmware — BLE sensor nodes + ESP32 hub                |
| `Project-Carl-IOS` | iOS app — user-facing dashboard                               |
| `Project-Norman`   | **Cloud — ingest, time-series storage, REST API, ML**         |

It runs three processes:

- **mosquitto** — MQTT broker that receives telemetry from Carl hubs.
- **ingest** ([apps/ingest](apps/ingest)) — validates messages and writes to Postgres.
- **api** ([apps/api](apps/api)) — FastAPI for the iOS app (auth, hubs, sensors, readings, predictions).

Storage is Postgres + TimescaleDB. ML is a scheduled job under [apps/ml](apps/ml) (placeholder until enough data accumulates).

## Contracts (the synchronization point with Carl and Carl-IOS)

- **Carl → Norman:** MQTT, see [docs/ingest-protocol.md](docs/ingest-protocol.md). Pydantic source of truth at [packages/schemas/telemetry.py](packages/schemas/telemetry.py).
- **Carl-IOS → Norman:** REST, see [docs/api.md](docs/api.md). OpenAPI spec auto-served at `/openapi.json`.

## Quickstart (local, no cloud needed)

```bash
cp .env.example .env
make dev                                   # docker compose up -d
make migrate                               # alembic upgrade head
make seed                                  # demo user + hub-001 + node-3
python scripts/fake_publisher.py           # publishes BME680-shaped readings every 5s

# in another shell — get a token, then read latest:
TOKEN=$(curl -s -X POST localhost:8000/v1/auth/login \
  -d "username=demo@norman.local&password=demodemo1" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/v1/sensors/node-3/latest | python -m json.tool

open http://localhost:8000/docs            # Swagger UI — what Carl-IOS codegens against
```

## Deploy (GCP free tier)

Terraform under [infra/terraform/](infra/terraform/) provisions a free-tier `e2-micro` VM, static IP, and a GCS bucket for ML artifacts. **Not applied yet** — see [infra/terraform/README.md](infra/terraform/README.md) when ready.

## Layout

```
apps/
  api/        FastAPI service (Dockerfile, routers, auth, models)
  ingest/     MQTT → Postgres worker (Dockerfile)
  ml/         training + inference (placeholder)
packages/
  schemas/    shared Pydantic — telemetry contract
docs/         architecture, ingest protocol, REST API
infra/
  mosquitto/  broker config (local dev anonymous; prod is mTLS)
  terraform/  GCP free-tier provisioning
migrations/   Alembic
scripts/
  fake_publisher.py   simulates a Carl hub for local smoke tests
tests/        pytest
```
