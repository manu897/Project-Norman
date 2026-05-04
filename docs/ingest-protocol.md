# Ingest protocol — Carl → Norman over MQTT

This is the contract Carl firmware (`Project-Carl`) implements as a publisher, and Norman ingest (`apps/ingest`) implements as a subscriber. The Pydantic source of truth lives at [`packages/schemas/telemetry.py`](../packages/schemas/telemetry.py).

## Transport

- Protocol: **MQTT 3.1.1 or 5**
- Broker: Mosquitto running in the Norman stack
- Production: TLS on **8883**, per-hub **mTLS** client cert
- Local dev: plain on **1883**, anonymous

## Topic

```
carl/{hub_id}/sensor/{sensor_id}/telemetry
```

- `hub_id` — stable identifier of the ESP32 hub (e.g. its MAC, or a configured device ID)
- `sensor_id` — stable identifier of the BLE sensor node
- QoS **1**, retained **false**

Norman subscribes to `carl/+/sensor/+/telemetry`.

## Payload

UTF-8 JSON, single object per message.

```json
{
  "ts": "2026-04-30T18:30:00Z",
  "hub_id": "hub-001",
  "sensor_id": "node-3",
  "metrics": {
    "temperature_c": 24.3,
    "humidity_pct": 61.2,
    "pressure_hpa": 1013.2,
    "voc_index": 145,
    "battery_v": 3.71,
    "rssi_dbm": -67
  }
}
```

| Field       | Type              | Notes                                                 |
| ----------- | ----------------- | ----------------------------------------------------- |
| `ts`        | ISO 8601 UTC      | When the sample was taken on the node, not published. |
| `hub_id`    | string, ≤64 chars | Must match the topic segment.                         |
| `sensor_id` | string, ≤64 chars | Must match the topic segment.                         |
| `metrics`   | object<str,float> | Keys below are recommended; unknown keys are accepted and stored. |

### Recommended metric keys

| Key             | Unit          | Source            |
| --------------- | ------------- | ----------------- |
| `temperature_c` | °C            | BME680            |
| `humidity_pct`  | % RH          | BME680            |
| `pressure_hpa`  | hPa           | BME680            |
| `voc_index`     | unitless 0–500| BME680 gas sensor |
| `battery_v`     | volts         | node ADC          |
| `rssi_dbm`      | dBm (negative)| BLE link, hub-side|

If Carl needs to report a metric that isn't listed, it can — Norman will store it. Add it to this table and to `KNOWN_METRICS` in `packages/schemas/telemetry.py` so it's documented.

## Authentication (production)

- Each hub gets a unique X.509 client cert signed by Norman's private CA.
- Mosquitto is configured with `require_certificate true` and `use_identity_as_username true`.
- The CN of the cert MUST equal the `hub_id` segment in the topic — Mosquitto's ACL enforces a hub can only publish under its own `carl/{cn}/...` prefix.

For local dev: anonymous, no TLS.

## Failure modes

- **Malformed JSON** — Norman drops with a warning log. Carl should not retry; fix the schema.
- **Validation error** (Pydantic) — same as above.
- **Norman unreachable** — Carl SHOULD buffer recent samples in flash and replay on reconnect (QoS 1 already guarantees broker-side delivery once the hub is back online and the broker is up).
- **Schema evolution** — backwards-compatible (adding a new metric key) is safe today. A renamed or removed key is a breaking change and must be coordinated.
