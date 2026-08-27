# Norman architecture

## Where Norman fits

Norman is the data + intelligence side of a three-repo system:

| Repo               | Role                                                                     |
| ------------------ | ------------------------------------------------------------------------ |
| Project-Carl       | Firmware — BLE BTHome plant/room/camera nodes + ESP32 hub + M5Paper      |
| Project-Carl-IOS   | iOS app — primary user-facing dashboard                                  |
| **Project-Norman** | **Cloud — long-term storage, off-LAN read fallback, per-plant ML**       |

The Carl hub is the central data plane on the LAN. Norman is **not** in the real-time path: the hub aggregates BLE BTHome adverts locally, then pushes a batch to Norman on a schedule. The iOS app talks to the hub directly when on home Wi-Fi and falls back to Norman when off-network.

```
[Plant probe] [Room ambient] [Camera] ─BTHome (AES-CCM)─▶  Carl hub
                                                            │
            LAN ◀── HTTP (carl-hub.local) ──────────────────┘  ── MQTT publish (carl/{site}/{node}) ──▶  Norman
            │                                                                                              │
       iOS app (primary)                                                                          iOS app (fallback, off-LAN)
                                                                                                           │
                                                                                                      ML / long-term storage
```

The hub publishes one MQTT message per node every ~30s (continuous, not batched — see [docs/ingest-protocol.md](ingest-protocol.md)). A second HTTPS POST batch path is also available for richer payloads and backfills.

## Three node kinds

The hub keeps everything in one `Node` collection but tags each with a `kind`:

| Kind | Hardware (Carl) | Reports |
|---|---|---|
| `plant` | XIAO nRF52840 + capacitive soil probe + BME280 | `soil_pct`, `battery_pct`, optional T/H/lux |
| `room` | Nordic Thingy:53 (USB) | `temperature_c`, `humidity_pct`, `pressure_hpa`, `illuminance_lux` |
| `camera` | XIAO ESP32-S3 Sense | `battery_pct` heartbeat (images stay on the hub) |

Plant nodes carry a `room_id` — they live in a room. The **hub** owns this assignment (the user sets it in the iOS app, which writes to the hub) and includes it in every batch. Norman stores what the hub says — no Norman→hub sync. This is `kind` internally (the `nodes.kind` DB column); the public API field is `node_type` — see [docs/api.md](api.md).

The hub is authoritative on `node_type`/`room_id` on *every* MQTT message, not just first insert — a node ingested wrong before the hub carried these fields (or before a firmware update added them) self-heals on its next publish rather than staying stuck. An older/partial message that omits the fields never clobbers a value a previous message already set. See [docs/ingest-protocol.md](ingest-protocol.md).

When iOS asks for a plant's current state, both the hub (LAN) and Norman (cloud) return the joined view: plant probe soil/battery + that room's ambient T/H/P/lux.

## Runtime processes

Four containers:

1. **postgres** — Postgres 16 + TimescaleDB extension. Stores users, hubs, rooms, nodes, readings (hypertable), predictions.
2. **mosquitto** — MQTT broker (Eclipse Mosquitto 2). Anonymous on 1883 in local dev; TLS + password auth in prod.
3. **api** (`apps/api`) — FastAPI:
   - **Read endpoints** mirror the hub's `/api/nodes/*` so the iOS app speaks one shape against both. JWT auth. Every endpoint scopes to `current_user`'s own hubs (`Hub.owner_id == user.id`) — `GET /v1/nodes` resolves each plant's room and latest readings with a fixed 3 batched queries regardless of node count, not one round-trip per node.
   - **HTTPS batch ingest** `POST /v1/hubs/{hub_id}/batch` — per-hub bearer, rich payload, alternate path.
   - **Admin (superuser only)** — `/v1/admin/*`, the one deliberate exception to per-user scoping: unscoped by ownership, for a single operator account to see the whole deployment (users, hubs, nodes, aggregate stats). Gated by `User.is_superuser`, which has no self-service grant path — flipped directly in Postgres. See [docs/api.md](api.md#admin-superuser-only).
   - OpenAPI auto-generated at `/openapi.json`.
4. **ingest** (`apps/ingest`) — long-running MQTT subscriber. Listens to `carl/+/+`, validates `NodeMessage`, writes `readings` rows + upserts `Node` records. Drops messages from hubs that haven't been registered via `POST /v1/hubs` first.

The ML pipeline (`apps/ml/`) is a scheduled job, not a long-running process. It joins each plant's readings with its assigned room's ambient, runs a per-plant model, and writes to `predictions`. Currently a stub heuristic; real model lands once enough data accumulates.

## Storage

- `users` — auth principals
- `hubs` — owned by users, with `api_token_hash` for upload auth
- `rooms` — hub-scoped (PK is `(id, hub_id)`); created on first batch from the hub
- `nodes` — `kind` discriminator. Plant nodes carry `room_id` and `species`.
- `readings` — time-series **hypertable**, long format `(ts, node_id, metric, value)`
- `predictions` — per-plant ML output, `jsonb` payload

Long-format `readings` lets new metrics be added without migrations. `Reading` Pydantic model is `extra="ignore"`, so the hub can ship a new metric key before Norman documents it.

## Cloud target

GCP always-free tier — `e2-micro` VM is always-free in `us-west1` / `us-central1` / `us-east1` (one per project). Both containers run on the single VM. GCS bucket holds ML model artifacts. Cloudflare proxied DNS terminates TLS in front. Provisioned by `infra/terraform/`. Not actually $0 end-to-end — the external static IP is billed regardless of the free tier, ~£2.75/mo; see [infra/terraform/README.md](../infra/terraform/README.md#what-this-actually-costs).

## Local dev

`docker-compose up` brings up postgres + mosquitto + api + ingest on the developer's laptop. Two smoke-test scripts:

- `scripts/fake_hub_publish.py` — MQTT path, mirrors what Carl actually does (continuous publish on `carl/hub-001/aabbccddeeff`).
- `scripts/fake_hub_post.py` — HTTPS batch path, sends one batch with rooms + plant + camera.

See [README.md](../README.md) for the smoke-test recipe.
