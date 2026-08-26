# Ingest protocols — Carl → Norman

Norman accepts telemetry over **two paths in parallel**. Carl's `firmware/hub/main/norman_uplink.c` (Phase 3h, shipped 2026-06-26) uses MQTT. The HTTPS batch path stays for richer payloads, manual backfills, and alternate clients.

| Path | Used by | Cadence | Payload |
|---|---|---|---|
| **MQTT** | Carl hub (`CONFIG_CARL_NORMAN_ENABLE=y`) | Continuous, ~30s | Flat per-node, no `ts` |
| **HTTPS batch** | Future Carl modes, manual backfill, tools | Per request | Rich: rooms + nodes + samples |

Both write to the same `readings` hypertable and `nodes` table.

---

## Path 1 — MQTT publish (primary; what Carl ships)

Carl's `firmware/hub/main/norman_uplink.c` is the source. Header comment:
> *"This is the Carl↔Norman boundary — continuous MQTT, not a daily HTTPS POST."*

### Transport

- **Broker URI** the hub connects to: `CONFIG_CARL_NORMAN_BROKER_URI` (use `mqtts://` in prod for TLS).
- **Auth:** MQTT username + password from the hub's menuconfig.
- **Topic:** `carl/{site_id}/{node_id}` where `site_id` is `CONFIG_CARL_NORMAN_SITE_ID` (≡ Norman's `hub_id`).
- **QoS:** 1, retain false.
- **Cadence:** every `CONFIG_CARL_NORMAN_INTERVAL_SEC` (default 30, range 5–3600).

Norman's ingest worker (`apps/ingest`) subscribes to `carl/+/+`.

### Payload (`NodeMessage`)

UTF-8 JSON, single object per message. Exactly the shape `publish_node()` emits:

```json
{
  "node": "aabbccddeeff",
  "mac": "AA:BB:CC:DD:EE:FF",
  "name": "Bedroom Monstera",
  "online": true,
  "node_type": "plant",
  "room_id": "living-room",
  "soil_pct": 41.0,
  "temperature_c": 23.1,
  "humidity_pct": 58.0,
  "pressure_hpa": 1013.2,
  "illuminance_lux": 420,
  "battery_pct": 78
}
```

| Field | Notes |
|---|---|
| `node` | Node id; MUST match the last topic segment. Mismatched messages are dropped. |
| `mac`, `name` | Node identity. Stored on `nodes`. |
| `online` | Hub-computed online flag. Defaults to true if absent. |
| `node_type` | Optional, `plant` \| `room`. Absent on older firmware. **Authoritative on every message when present** — see below. |
| `room_id` | Optional, omitted (not sent as `""`) when a plant has no room assigned. Same authoritative-when-present treatment as `node_type`. |
| metric fields | All nullable; only present-and-non-null metrics get a row in `readings`. |

**No `ts` field.** Norman stamps `readings.ts = NOW()` on receipt. This loses up to one publish interval of fidelity (≤30s typical) — acceptable for personal-scale time-series.

**No `calibration`.** Carl's MQTT path doesn't carry it; only the HTTPS batch path does.

**History:** `node_type`/`room_id` were added to the wire format after the fact — the hub's `carl_node_snapshot_t` originally didn't carry them at all, so every MQTT-ingested node was silently hardcoded to `kind=plant` on first insert with no way to ever correct it short of a manual `UPDATE nodes` in Postgres. Confirmed live in production: a real Thingy:53 room sensor stayed misclassified as a plant indefinitely. Fixed on both sides — the hub now sends both fields, and ingest treats them as authoritative on *every* message, not just first insert, so a node stuck wrong from before this fix self-heals on its very next publish.

### Ingest behavior

For each message:
1. Parse topic → `(site_id, node_id)`. Malformed topics dropped.
2. Validate payload as `NodeMessage`. Validation errors dropped + logged.
3. Verify `payload.node == topic node_id`. Mismatches dropped.
4. **Verify `Hub(id=site_id)` exists.** If not, drop + log — the user must register the hub first via `POST /v1/hubs`. Norman does NOT auto-create hubs from MQTT messages (intentional: forces clean ownership).
5. Upsert `Node` row (id, hub_id, mac, name, battery_pct, last_seen_at). `kind`/`room_id` are refreshed **only when the message actually includes them** — an older/partial message never clobbers a value a previous message (or an HTTPS batch, or a manual correction) already set.
6. Insert one `readings` row per present metric.
7. Update `hubs.last_seen_at`.

### Errors (none returned to the publisher)

MQTT is fire-and-forget at the application layer — Norman doesn't send error responses. Drops are visible only in `apps/ingest` logs.

---

## Path 2 — HTTPS batch upload (alternate)

Same as before this round — see the section below for the full shape. Carl could swap to this in the future; tools and manual backfills use it today.

### Endpoint

```
POST /v1/hubs/{hub_id}/batch
Authorization: Bearer <hub_api_token>
Content-Type: application/json
```

- `hub_api_token` is per-hub, issued by `POST /v1/hubs` (shown once), stored bcrypt-hashed in `hubs.api_token_hash`.

### Body (`HubBatchUpload`)

```jsonc
{
  "hub_version": "0.2.0",
  "generated_at": "2026-06-26T18:00:00Z",
  "rooms": [{ "id": "room-bedroom", "name": "Bedroom" }],
  "nodes": [
    {
      "id": "aabbccddeeff",
      "kind": "plant",          // or "room" or "camera"
      "mac": "AA:BB:CC:DD:EE:FF",
      "name": "Bedroom Monstera",
      "room_id": "room-bedroom",
      "species": "monstera_deliciosa",
      "calibration": { "soil_dry_pct": 25, "soil_wet_pct": 65, "battery_low_pct": 15, "offline_after_minutes": 30 },
      "samples": [
        { "ts": "2026-06-26T17:55:00Z", "soil_pct": 41.0, "battery_pct": 78 }
      ]
    }
  ]
}
```

Unlike the MQTT path, this carries explicit timestamps per sample, kind/room/species/calibration, and can include multiple nodes per request.

### Response

- `202 Accepted` with `{"rooms_seen": R, "nodes_seen": N, "samples_inserted": M}`.
- `401 Unauthorized` — bad token.
- `422 Unprocessable Entity` — schema validation failed.

### Idempotency (both paths)

Both paths dedupe by `(ts, node_id, metric)` on the readings hypertable. Retries are no-ops.

---

## Pydantic source of truth

- MQTT: `NodeMessage` in [`packages/schemas/telemetry.py`](../packages/schemas/telemetry.py).
- HTTPS: `HubBatchUpload` / `RoomBatch` / `NodeBatch` / `Reading` / `Calibration` in the same file.

When Carl ships a new metric in `firmware/hub/main/node_registry.h::carl_reading_t`, add it to `KNOWN_METRICS` and the relevant Pydantic models. Pydantic's `extra="ignore"` on both shapes means a new metric arriving early just falls on the floor instead of breaking the ingest.
