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
| `Project-Carl`     | Firmware — BLE BTHome plant/room/camera nodes + ESP32 hub + M5Paper    |
| `Project-Carl-IOS` | iOS app — primary user-facing dashboard                                |
| `Project-Norman`   | **Cloud — long-term storage, off-LAN read fallback, per-plant ML**     |

Three node kinds — **plant** (soil probe), **room** (ambient T/H/P/lux), **camera** (image stills stay on the hub, only battery heartbeats reach Norman). Plant nodes carry a `room_id` so we can serve a joined plant+room snapshot the same way the hub does on the LAN.

It runs **four** processes:

- **postgres** — Postgres 16 + TimescaleDB extension.
- **mosquitto** — MQTT broker; Carl hubs publish here.
- **api** ([apps/api](apps/api)) — FastAPI. Read endpoints mirror the hub's `/api/nodes/*` so the iOS app uses one shape against both LAN and cloud. Also exposes `POST /v1/hubs/{id}/batch` for the HTTPS alternate path.
- **ingest** ([apps/ingest](apps/ingest)) — MQTT subscriber on `carl/+/+`. The actual ingest path Carl uses.

ML is a scheduled job under [apps/ml](apps/ml) — per-plant health + watering predictions. Currently a stub heuristic; real model once data accumulates.

## Contracts (the synchronization point with Carl and Carl-IOS)

- **Carl hub → Norman (primary):** MQTT publish on `carl/{site_id}/{node_id}`, every ~30s. See [docs/ingest-protocol.md](docs/ingest-protocol.md). Pydantic source of truth: `NodeMessage` in [packages/schemas/telemetry.py](packages/schemas/telemetry.py).
- **Carl hub → Norman (alternate):** HTTPS POST to `/v1/hubs/{id}/batch`. Same doc, richer shape (`HubBatchUpload`).
- **Carl-IOS → Norman:** REST, see [docs/api.md](docs/api.md). Same `Node` / `Reading` / `History` shapes as the hub's `Project-Carl-IOS/api/openapi.yaml`.

## Quickstart (local, no cloud needed)

```bash
cp .env.example .env
make dev                                   # postgres + mosquitto + api + ingest
make migrate                               # alembic upgrade head
make seed                                  # demo user + hub-001 (writes .demo-hub-token)

# --- MQTT path (what Carl actually does) ---
make fake-publish                          # streams flat NodeMessage to carl/hub-001/aabbccddeeff
# (Ctrl+C after a few cycles)

# --- HTTPS batch path (alternate, richer) ---
make fake-batch                            # POSTs 1 room + 1 plant + 1 camera in one batch

# Read it all back through Norman's HTTP API:
TOKEN=$(curl -s -X POST localhost:8000/v1/auth/login \
  -d "username=demo@norman.local&password=demodemo1" \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/v1/rooms | python -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" \
  "localhost:8000/v1/nodes?kind=plant" | python -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/v1/nodes/aabbccddeeff/snapshot | python -m json.tool   # joined view
docker compose run --rm api python -m apps.ml.train                      # writes a placeholder prediction
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/v1/nodes/aabbccddeeff/predictions | python -m json.tool

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
