# Project-Norman

## Summary
Project Norman is named after scientist Norman Borlaug, who is the man behind the green revolution and father of green revolution.

The project is addressing the monitoring issue of the agricultural field using IOT based sensor. This project will investigate and address the issues whole as a system (From Sensor to data management and Machine learning models are used to predict the crop yield and health)

The project details are in [Confluence](https://arttme.atlassian.net/l/cp/kPyWw9M7) and managed using monday.com


## Author:

[Manideep Reddy Tamma](mailto:manideep.2251.tamma@gmail.com)

[LinkedIn](https://www.linkedin.com/in/manideep-reddy-tamma/)

---

## Status

**Live**, deployed on GCP (`us-central1`, e2-micro, always-free tier) as of 2026-08-25:

- API: `https://norman.manideepreddy.com` (Cloudflare-proxied HTTPS via Caddy)
- MQTT broker: `mqtts://mqtt.manideepreddy.com:8883` (TLS, DNS-only — not Cloudflare-proxied, MQTT can't be)

Verified end-to-end: a Carl-shaped MQTT publish → `apps/ingest` → Postgres → `GET /v1/nodes` over public HTTPS, returning the correct Carl-compatible JSON shape. Real Carl hub hardware hasn't been pointed at it yet — see [infra/terraform/README.md](infra/terraform/README.md) §7 for how, once flashed.

## What's in this repo

Norman is the **data + intelligence** side of a three-repo system:

| Repo               | Role                                                                   |
| ------------------ | ---------------------------------------------------------------------- |
| `Project-Carl`     | Firmware — BLE BTHome plant/room nodes + camera + ESP32 hub + M5Paper  |
| `Project-Carl-IOS` | iOS app — primary user-facing dashboard                                |
| `Project-Norman`   | **Cloud — long-term storage, off-LAN read fallback, per-plant ML**     |

Two node types at the API surface — **plant** (soil probe, optionally joined to a room) and **room** (ambient T/H/P/lux for a whole room). This mirrors Carl's shipped contract exactly (`node_type` enum, `Project-Carl/documents/api/openapi.yaml` v0.3.0): a plant node gets the room's latest ambient reading **grafted directly onto it** as an embedded `room` object — not a separate lookup. Camera nodes exist in Norman's own bookkeeping (battery heartbeats only; stills stay on the hub) but aren't part of the `node_type` enum Carl-IOS decodes, so they're excluded from `GET /v1/nodes` unless explicitly requested.

It runs **four** processes:

- **postgres** — Postgres 16 + TimescaleDB extension.
- **mosquitto** — MQTT broker; Carl hubs publish here.
- **api** ([apps/api](apps/api)) — FastAPI. Read endpoints mirror the hub's `/api/nodes/*` so the iOS app uses one shape against both LAN and cloud. Also exposes `POST /v1/hubs/{id}/batch` for the HTTPS alternate path.
- **ingest** ([apps/ingest](apps/ingest)) — MQTT subscriber on `carl/+/+`. The actual ingest path Carl uses.

In production, a fifth process — **Caddy** — fronts the API with a real TLS cert, since Cloudflare's proxy can't forward to port 8000 directly. See `docker-compose.prod.yml` (GCP) or `docker-compose.home.yml` (self-hosted alternative via Cloudflare Tunnel, no public broker needed since the hub and Norman share a LAN).

ML is a scheduled job under [apps/ml](apps/ml) — per-plant health + watering predictions. Currently a stub heuristic; real model once data accumulates.

## Contracts (the synchronization point with Carl and Carl-IOS)

- **Carl hub → Norman (primary):** MQTT publish on `carl/{site_id}/{node_id}`, every ~30s. See [docs/ingest-protocol.md](docs/ingest-protocol.md). Pydantic source of truth: `NodeMessage` in [packages/schemas/telemetry.py](packages/schemas/telemetry.py).
- **Carl hub → Norman (alternate):** HTTPS POST to `/v1/hubs/{id}/batch`. Same doc, richer shape (`HubBatchUpload`).
- **Carl-IOS → Norman:** REST, see [docs/api.md](docs/api.md). `node_type` / `room_id` / embedded `room` match the hub's `Project-Carl-IOS/api/openapi.yaml` and `CarlApp/Models/Plant.swift` exactly — pinned by [tests/test_node_out_schema.py](tests/test_node_out_schema.py) so a future rename fails loudly instead of silently breaking the app's JSON decode.

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
  localhost:8000/v1/nodes | python -m json.tool                          # plant+room only by default —
                                                                           # node_type/room_id/embedded room,
                                                                           # matching Carl-IOS exactly
docker compose run --rm api python -m apps.ml.train                      # writes a placeholder prediction
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/v1/nodes/aabbccddeeff/predictions | python -m json.tool

open http://localhost:8000/docs            # Swagger UI — same Node/Reading shapes as the hub
```

## Deploy

**GCP free tier (current):** Terraform under [infra/terraform/](infra/terraform/) provisions a free-tier `e2-micro` VM, static IP, and a GCS bucket for ML artifacts, with Caddy terminating TLS for the API. Full runbook — including the ~$3.65/mo real cost (the external IPv4, not the compute) and the budget-alert step — in [infra/terraform/README.md](infra/terraform/README.md).

**Self-hosted alternative:** [infra/home/README.md](infra/home/README.md) — run Norman on a spare always-on Ubuntu machine on the same LAN as the Carl hub, reached from outside via Cloudflare Tunnel. Architecturally simpler (no public MQTT broker, no cert renewal dance, since the hub and Norman share a network) but requires a machine that's genuinely always on — Carl's MQTT publish loop has no buffering, so downtime here is silently-dropped telemetry, not a queued backlog.

## Layout

```
apps/
  api/          FastAPI service: auth, hubs, rooms, nodes, ingest, predictions
  ingest/       MQTT subscriber — Carl's actual ingest path
  ml/           training + inference (placeholder heuristic)
packages/
  schemas/      shared Pydantic — Carl-hub→Norman contracts (NodeMessage, HubBatchUpload)
docs/           architecture, ingest protocol, REST API (node_type/room shape, pinned)
infra/
  terraform/    GCP free-tier provisioning + deploy runbook (current deployment)
  caddy/        TLS termination in front of the API (Cloudflare can't proxy :8000 directly)
  mosquitto/    broker configs — dev (anonymous), prod (public TLS 8883 + internal 1883), home
  home/         self-hosted alternative: Ubuntu + Cloudflare Tunnel, no public broker needed
migrations/     Alembic
scripts/
  fake_hub_publish.py   simulates a Carl hub over MQTT — the real ingest path
  fake_hub_post.py      simulates a Carl hub batch upload — the alternate HTTPS path
  backup_postgres.sh    nightly Postgres dump → GCS artifacts bucket
tests/          pytest — includes a contract-pinning test against Carl's Node shape
docker-compose.yml         base stack: postgres + mosquitto + api + ingest
docker-compose.prod.yml    + Caddy, for the GCP deployment
docker-compose.home.yml    + cloudflared, for the self-hosted alternative
```
