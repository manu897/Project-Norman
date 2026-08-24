"""Carl-hub → Norman HTTPS batch upload contract.

Mirrors the end-state hub upload shape: three node kinds (plant / room / camera),
hub-scoped rooms, plant↔room assignment carried on each plant node.

Source of truth for the shared `Reading` shape is
`Project-Carl-IOS/api/openapi.yaml`. If a metric is added to the hub's
`Reading` / `carl_reading_t`, add it to `KNOWN_METRICS` here.

Forward-compat: `Reading` accepts unknown metric keys (Pydantic ignores them
on parse). To make a new metric *queryable* on Norman, add it to KNOWN_METRICS.
"""

from datetime import datetime
from enum import Enum
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


class NodeKind(str, Enum):
    plant = "plant"
    room = "room"
    camera = "camera"


class Calibration(BaseModel):
    """Per-node thresholds. Defaults match the iOS spec."""

    model_config = ConfigDict(extra="forbid")

    soil_dry_pct: float = 25.0
    soil_wet_pct: float = 65.0
    battery_low_pct: int = 15
    offline_after_minutes: int = 30


class Reading(BaseModel):
    """One time-stamped sample. All metrics nullable — node sends what it has."""

    model_config = ConfigDict(extra="ignore")  # forward-compat: ignore unknown metrics

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


class RoomBatch(BaseModel):
    """Room metadata as part of a hub batch. Identified hub-scoped."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=255)]


class NodeBatch(BaseModel):
    """One node's contribution to a hub batch. Kind discriminates downstream behavior."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    kind: NodeKind = NodeKind.plant
    mac: Annotated[str, Field(min_length=11, max_length=17)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    # Plant-only fields. Hub omits them (or sends null) for room/camera nodes.
    room_id: str | None = None
    species: str | None = None
    calibration: Calibration | None = None
    samples: list[Reading] = Field(default_factory=list)


class HubBatchUpload(BaseModel):
    """POST /v1/hubs/{hub_id}/batch body (HTTPS path)."""

    model_config = ConfigDict(extra="forbid")

    hub_version: str
    generated_at: datetime
    rooms: list[RoomBatch] = Field(default_factory=list)
    nodes: list[NodeBatch] = Field(default_factory=list)


class NodeMessage(BaseModel):
    """One MQTT message on topic `carl/{site_id}/{node_id}`.

    Mirrors what Carl's `firmware/hub/main/norman_uplink.c::publish_node()`
    serializes. Flat per-node, no `ts` (Norman stamps receipt time), no
    calibration / kind / room_id / species (Carl doesn't send them on this
    path). All metric fields nullable.
    """

    model_config = ConfigDict(extra="ignore")  # forward-compat: tolerate new keys

    node: Annotated[str, Field(min_length=1, max_length=64)]
    mac: Annotated[str, Field(min_length=11, max_length=17)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    online: bool = True

    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    soil_pct: float | None = None
    illuminance_lux: float | None = None
    battery_pct: int | None = None

    def metric_pairs(self) -> list[tuple[str, float]]:
        """(metric, value) for every present metric. KNOWN_METRICS only."""
        out: list[tuple[str, float]] = []
        for metric in KNOWN_METRICS:
            v = getattr(self, metric, None)
            if v is not None:
                out.append((metric, float(v)))
        return out
