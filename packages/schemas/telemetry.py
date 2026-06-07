"""Carl→Norman HTTPS batch upload contract.

Mirror of `Project-Carl-IOS/api/openapi.yaml` — same field names, same
nullability, so the iOS app speaks one shape whether it's hitting the LAN
hub or the cloud Norman. If a metric is added to the hub's `Reading` /
`carl_reading_t`, add it here too and update `KNOWN_METRICS`.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

KNOWN_METRICS: tuple[str, ...] = (
    "temperature_c",
    "humidity_pct",
    "pressure_hpa",
    "soil_pct",
    "illuminance_lux",
    "battery_pct",
)


class Calibration(BaseModel):
    """Per-node thresholds. Defaults match the iOS spec."""

    model_config = ConfigDict(extra="forbid")

    soil_dry_pct: float = 25.0
    soil_wet_pct: float = 65.0
    battery_low_pct: int = 15
    offline_after_minutes: int = 30


class Reading(BaseModel):
    """One time-stamped sample. All metrics nullable — hub sends what it has."""

    model_config = ConfigDict(extra="ignore")  # forward-compat: ignore new metrics

    ts: datetime
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    soil_pct: float | None = None
    illuminance_lux: float | None = None
    battery_pct: int | None = None

    def to_long_rows(self, node_id: str) -> list[tuple[datetime, str, str, float]]:
        """Flatten into (ts, node_id, metric, value) tuples for DB insert."""
        rows: list[tuple[datetime, str, str, float]] = []
        for metric in KNOWN_METRICS:
            value = getattr(self, metric, None)
            if value is not None:
                rows.append((self.ts, node_id, metric, float(value)))
        return rows


class NodeBatch(BaseModel):
    """One plant node's contribution to a hub batch."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    mac: Annotated[str, Field(min_length=11, max_length=17)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    calibration: Calibration | None = None
    samples: list[Reading] = Field(default_factory=list)


class HubBatchUpload(BaseModel):
    """POST /api/hubs/{hub_id}/batch body."""

    model_config = ConfigDict(extra="forbid")

    hub_version: str
    generated_at: datetime
    nodes: list[NodeBatch] = Field(default_factory=list)
