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

| Repo               | Role                                                                   |
| ------------------ | ---------------------------------------------------------------------- |
| `Project-Carl`     | Firmware — BLE BTHome sensor/camera nodes + ESP32 hub + M5Paper reader |
| `Project-Carl-IOS` | iOS app — primary user-facing dashboard                                |
| `Project-Norman`   | **Cloud — long-term storage, off-LAN read fallback, ML predictions**   |

It runs **two** processes (no broker, no ingest worker):

- **postgres** — Postgres 16 + TimescaleDB extension.
- **api** ([apps/api](apps/api)) — FastAPI. Read endpoints mirror the hub's `/api/nodes/*` so the iOS app uses one shape against both LAN and cloud. Ingest is an HTTP endpoint: `POST /v1/hubs/{hub_id}/batch`.

ML is a scheduled job under [apps/ml](apps/ml) (placeholder until enough data accumulates).

## Contracts (the synchronization point with Carl and Carl-IOS)

- **Carl hub → Norman:** HTTPS batch upload, see [docs/ingest-protocol.md](docs/ingest-protocol.md). Pydantic source of truth at [packages/schemas/telemetry.py](packages/schemas/telemetry.py).
- **Carl-IOS → Norman:** REST, see [docs/api.md](docs/api.md). Same `Node` / `Reading` / `History` shapes as the hub's `Project-Carl-IOS/api/openapi.yaml`.

## Quickstart (local, no cloud needed)

```bash
cp .env.example .env
make dev                                   # docker compose up -d (postgres + api)
make migrate                               # alembic upgrade head
make seed                                  # demo user + hub-001 (writes .demo-hub-token)
make fake-batch                            # POSTs a batch to /v1/hubs/hub-001/batch

# in another shell — get a user JWT, then read the node back through Norman:
TOKEN=$(curl -s -X POST localhost:8000/v1/auth/login \
  -d "username=demo@norman.local&password=demodemo1" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/v1/nodes | python -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8000/v1/nodes/aabbccddeeff/history?range=24h" | python -m json.tool

open http://localhost:8000/docs            # Swagger UI — same Node/Reading shapes as the hub
```

## Deploy (GCP free tier)

Terraform under [infra/terraform/](infra/terraform/) provisions a free-tier `e2-micro` VM, static IP, and a GCS bucket for ML artifacts. **Not applied yet** — see [infra/terraform/README.md](infra/terraform/README.md) when ready.

## Layout

```
apps/
  api/        FastAPI service: auth, hubs, nodes, ingest, predictions
  ml/         training + inference (placeholder)
packages/
  schemas/    shared Pydantic — Carl-hub→Norman batch contract
docs/         architecture, ingest protocol, REST API
infra/
  terraform/  GCP free-tier provisioning
migrations/   Alembic
scripts/
  fake_hub_post.py   simulates a Carl hub batch upload for local smoke tests
tests/        pytest
```
