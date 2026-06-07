# Norman architecture

## Where Norman fits

Norman is the data + intelligence side of a three-repo system:

| Repo               | Role                                                                     |
| ------------------ | ------------------------------------------------------------------------ |
| Project-Carl       | Firmware — BLE BTHome sensor/camera nodes + ESP32 hub + M5Paper reader   |
| Project-Carl-IOS   | iOS app — primary user-facing dashboard                                  |
| **Project-Norman** | **Cloud — long-term storage, off-LAN read fallback, ML predictions**     |

The Carl hub is the central data plane on the LAN. Norman is **not** in the real-time path: the hub aggregates BLE BTHome adverts locally, then pushes a batch to Norman on a schedule. The iOS app talks to the hub directly when on home Wi-Fi and falls back to Norman when off-network.

```
Sensor nodes  ─BTHome v2 adv (AES-CCM-128)─▶  Carl hub
                                              │
        LAN ◀── HTTP (carl-hub.local) ───────┘  ── daily HTTPS POST ──▶  Norman
        │                                                                 │
   iOS app (primary)                                              iOS app (fallback, off-LAN)
                                                                          │
                                                                     ML / long-term storage
```

## Runtime processes

Just **two** containers (postgres + api). No broker, no separate ingest worker — ingest is an HTTP endpoint on the api service.

1. **postgres** — Postgres 16 + TimescaleDB extension. Stores users, hubs, nodes, readings (hypertable), predictions.
2. **api** (`apps/api`) — FastAPI:
   - **Read endpoints** mirror the hub's `/api/nodes/*` so the iOS app speaks one shape against both. JWT auth.
   - **Ingest endpoint** `POST /v1/hubs/{hub_id}/batch` takes a hub batch. Per-hub bearer token auth.
   - OpenAPI auto-generated at `/openapi.json`.

The ML pipeline (`apps/ml`) is a scheduled job, not a long-running process. It reads from Postgres, writes models to GCS, and the `api` service loads them for inference.

## Storage

- `users` — auth principals
- `hubs` — owned by users, with `api_token_hash` for upload auth
- `nodes` — belong to hubs; mirror of the hub's `Node` schema (`id`, `mac`, `name`, `battery_pct`, `calibration` jsonb, `last_seen_at`)
- `readings` — time-series **hypertable**, long format `(ts, node_id, metric, value)`
- `predictions` — ML output, `jsonb` payload

Long-format `readings` lets new metrics be added without migrations.

## Cloud target

GCP always-free tier — `e2-micro` VM is always-free in `us-west1` / `us-central1` / `us-east1` (one per project), AWS `t2.micro` is only 12 months. Both containers run on the single VM. GCS bucket holds ML artifacts. Static IP + Cloudflare DNS in front. Provisioned by `infra/terraform/`.

## Local dev

`docker-compose up` brings up postgres + api on the developer's laptop. `scripts/fake_hub_post.py` simulates a Carl hub by POSTing a synthetic batch — useful for exercising the ingest endpoint and seeding the DB with plausible-looking data. See [README.md](../README.md) for the smoke-test recipe.
