# Ingest protocol — Carl hub → Norman over HTTPS

Carl hubs upload telemetry to Norman in **batches over HTTPS**. There is no MQTT broker in Norman; the hub keeps a rolling history buffer locally (BLE BTHome decoder writes into NVS) and POSTs to Norman on a schedule.

Source of truth for the `Reading` payload shape is `Project-Carl-IOS/api/openapi.yaml`. If that changes, update this doc and [`packages/schemas/telemetry.py`](../packages/schemas/telemetry.py) together.

## Endpoint

```
POST /v1/hubs/{hub_id}/batch
Authorization: Bearer <hub_api_token>
Content-Type: application/json
```

- `hub_id` is the same string the hub uses for itself on the LAN dashboard (`/api/health.hub_id`).
- `hub_api_token` is per-hub. The user gets it once at `POST /v1/hubs` time and provisions it on the hub via menuconfig (Phase 3a) or the captive portal (Phase 3f).
- Stored as a bcrypt hash on Norman in `hubs.api_token_hash`. Distinct from the user's JWT used for read endpoints.

## Request body

```json
{
  "hub_version": "0.1.0",
  "generated_at": "2026-05-04T18:00:00Z",
  "nodes": [
    {
      "id": "aabbccddeeff",
      "mac": "AA:BB:CC:DD:EE:FF",
      "name": "Bedroom Monstera",
      "calibration": {
        "soil_dry_pct": 25.0,
        "soil_wet_pct": 65.0,
        "battery_low_pct": 15,
        "offline_after_minutes": 30
      },
      "samples": [
        {
          "ts": "2026-05-04T17:55:00Z",
          "temperature_c": 24.3,
          "humidity_pct": 61.2,
          "pressure_hpa": 1013.2,
          "soil_pct": 41.0,
          "illuminance_lux": 320.0,
          "battery_pct": 78
        }
      ]
    }
  ]
}
```

| Field | Notes |
|---|---|
| `hub_version` | Hub firmware version string. Logged on Norman for support. |
| `generated_at` | When the hub assembled the batch (ISO 8601 UTC). Not the sample time. |
| `nodes[*].id` | Hex-string node id (lowercase, MAC-derived). Matches the hub's `Node.id`. |
| `nodes[*].mac` | `AA:BB:CC:DD:EE:FF`. |
| `nodes[*].name` | User-set plant name. Hub is authoritative. |
| `nodes[*].calibration` | Optional. If present, replaces the stored calibration for that node. |
| `nodes[*].samples[*]` | One `Reading` per sample, exactly the iOS spec's `Reading` schema. All metric fields nullable. |

### Recommended metric keys

Mirror the hub's `carl_reading_t`:

| Key | Unit | Source |
|---|---|---|
| `temperature_c` | °C | BME280 |
| `humidity_pct` | % RH | BME280 |
| `pressure_hpa` | hPa | BME280 |
| `soil_pct` | % (calibrated, 0–100) | capacitive soil probe |
| `illuminance_lux` | lux | VEML7700 |
| `battery_pct` | integer 0–100 | node coin-cell estimate |

Adding a new metric is backwards-compatible: Pydantic ignores unknown keys in `Reading`. To make it queryable on Norman, add it to `KNOWN_METRICS` in [`packages/schemas/telemetry.py`](../packages/schemas/telemetry.py).

## Response

- `202 Accepted` with `{"nodes_seen": N, "samples_inserted": M}`.
- `401 Unauthorized` if the bearer token doesn't match the stored hash for `{hub_id}`.
- `422 Unprocessable Entity` if the body fails schema validation. Hub should not retry; fix the payload.

## Idempotency

Norman dedups by `(ts, node_id, metric)` on insert (`ON CONFLICT DO UPDATE` against the readings hypertable). The hub can safely retry the same batch after a TCP/TLS blip — duplicates are no-ops.

The hub should still acknowledge `202` to garbage-collect its local buffer, but resending the same range on the next cycle is harmless.

## Cadence

- **Steady state:** once per 24h (overnight). Configurable via menuconfig.
- **Backfill:** on first connection after a long offline window, the hub may send multiple batches.

## TLS / auth notes

- Production Norman is served behind Cloudflare (or Cloud Run) over TLS. The hub validates against the system trust store baked into ESP-IDF.
- The bearer token is the only secret on the hub. If a hub is reflashed, the user re-issues a new token by deleting + re-creating the hub on Norman.
