"""Carl→Norman MQTT telemetry contract.

Single source of truth for the payload Carl firmware publishes and Norman
ingest consumes. If a metric is added or renamed here, update
docs/ingest-protocol.md and notify the Carl repo.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

KNOWN_METRICS: tuple[str, ...] = (
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "voc_index",
    "battery_v",
    "rssi_dbm",
)


class TelemetryPayload(BaseModel):
    """One MQTT message from a Carl sensor node, published via the hub."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts: datetime = Field(..., description="Sample timestamp, ISO 8601 UTC")
    hub_id: str = Field(..., min_length=1, max_length=64)
    sensor_id: str = Field(..., min_length=1, max_length=64)
    metrics: dict[str, float] = Field(
        ...,
        description="Metric name → value. Unknown keys are accepted and stored as-is.",
    )

    def flatten(self) -> list[tuple[datetime, str, str, float]]:
        """Yield (ts, sensor_id, metric, value) tuples for long-format insert."""
        return [(self.ts, self.sensor_id, m, v) for m, v in self.metrics.items()]
