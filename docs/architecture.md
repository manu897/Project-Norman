# Norman architecture

## Where Norman fits

Norman is the data + intelligence side of a three-repo system:

| Repo               | Role                                                          |
| ------------------ | ------------------------------------------------------------- |
| Project-Carl       | Zephyr firmware: BLE sensor nodes + ESP32 hub                 |
| Project-Carl-IOS   | iOS app — user-facing dashboard                               |
| **Project-Norman** | **Cloud: ingest, storage, REST API, ML for yield/health**     |

Carl pushes telemetry to Norman over MQTT. Carl-IOS reads it back over HTTPS.

```
   Carl hub (ESP32)                 Norman                              Carl-IOS
   ├─ MQTT publisher    ── mTLS ──▶ Mosquitto :8883
   │                                  │
   │                                  ▼
   │                                ingest worker ──▶ Postgres + TimescaleDB
   │                                                      │
   │                                                      ├──▶ FastAPI :8000  ◀── HTTPS ──┘
   │                                                      └──▶ ML pipeline (scheduled, GCS for artifacts)
```

## Runtime processes

Three Docker containers (one VM in production, `docker-compose` locally):

1. **mosquitto** — MQTT broker. TLS on 8883 in prod, plain on 1883 locally.
2. **ingest** (`apps/ingest`) — subscribes to `carl/+/sensor/+/telemetry`, validates with the Pydantic model in `packages/schemas/telemetry.py`, writes long-format rows to `readings`, updates `sensors.last_seen_at`.
3. **api** (`apps/api`) — FastAPI; serves the iOS app. JWT auth, hubs/sensors/readings/predictions endpoints. OpenAPI is auto-generated and served at `/openapi.json` for iOS Swift codegen.

The ML pipeline (`apps/ml`) is a scheduled job, not a long-running process. It reads from Postgres, writes models to GCS, and the `api` service loads them for inference.

## Storage

Postgres + TimescaleDB extension (free, OSS, runs in Docker). Schema:

- `users` — auth principals
- `hubs` — owned by users
- `sensors` — belong to hubs
- `readings` — time-series **hypertable**, long format `(ts, sensor_id, metric, value)`
- `predictions` — ML output, `jsonb` payload for flexibility

Long-format `readings` lets new metrics be added without migrations — useful while the firmware side is in flux.

## Cloud target

GCP always-free tier — `e2-micro` VM is always-free in `us-west1` / `us-central1` / `us-east1` (one per project), AWS `t2.micro` is only 12 months. All three services run on a single VM. GCS bucket holds ML artifacts. Static IP + Cloudflare DNS in front. Provisioned by `infra/terraform/`.

## Local dev

`docker-compose up` brings up the whole stack on the developer's laptop, no cloud needed. `scripts/fake_publisher.py` simulates a Carl hub feeding plausible BME680 readings every few seconds. See [README.md](../README.md) for the smoke-test recipe.
