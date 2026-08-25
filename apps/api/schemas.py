"""Pydantic request/response models for the Norman REST API.

Reading/Node/Calibration/History shapes mirror `Project-Carl-IOS/api/openapi.yaml`
so the iOS app speaks one contract for both LAN-hub and cloud-Norman paths.

IMPORTANT — `NodeOut` field names are load-bearing, not cosmetic. Carl's
authoritative hub spec (`Project-Carl/documents/api/openapi.yaml`, shipped
2026-08-24) and the iOS app's `CarlApp/Models/Plant.swift` both decode
`node_type` (not `kind`), a non-optional `room_id` (empty string, not null,
when unassigned), and an embedded `room: RoomEnv?` grafted directly onto
plant nodes — NOT a separate lookup. Norman's `/v1/nodes*` responses must
match this exactly or the real iOS app fails to parse them. Norman's own
`kind` enum still has a `camera` member for internal bookkeeping (Carl's
node_type enum only has plant/room) — see routers/nodes.py for how that's
kept from ever reaching this response model.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from packages.schemas.telemetry import Calibration, HubBatchUpload, NodeKind, Reading

__all__ = [
    "RegisterRequest",
    "TokenResponse",
    "HubCreate",
    "HubOut",
    "HubCreateOut",
    "RoomOut",
    "RoomDetailOut",
    "RoomEnv",
    "NodeOut",
    "SnapshotOut",
    "HistoryOut",
    "PredictionOut",
    "BatchAcceptedOut",
    "Reading",
    "Calibration",
    "HubBatchUpload",
    "NodeKind",
]


# --- Auth ---


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Hubs ---


class HubCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    location: str | None = None


class HubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: str | None
    last_seen_at: datetime | None
    created_at: datetime


class HubCreateOut(HubOut):
    """Hub-create response — includes the bearer token, exposed exactly once."""

    api_token: str


# --- Rooms ---


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hub_id: str
    name: str
    created_at: datetime


# --- Nodes (mirror of hub's Node schema: node_type/room_id/embedded room) ---


class RoomEnv(BaseModel):
    """A room node's latest ambient reading, grafted onto a plant node.

    Exact mirror of Carl's `RoomEnv` schema — field names and nullability
    must match, since `CarlApp/Models/Plant.swift::RoomEnv` decodes this
    directly off the `Node.room` key.
    """

    source: str  # id of the room node this came from
    ts: datetime
    temperature_c: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    illuminance_lux: float | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mac: str
    name: str
    node_type: NodeKind
    room_id: str
    hub_id: str
    species: str | None
    online: bool
    last_seen: datetime | None
    battery_pct: int | None
    latest: Reading | None
    calibration: Calibration | None
    room: RoomEnv | None = None


class RoomDetailOut(RoomOut):
    """A room + its assigned nodes (room-kind + plants in it)."""

    nodes: list[NodeOut]


class SnapshotOut(BaseModel):
    """Plant's joined view: plant probe readings + assigned room's ambient.

    Superseded by the `room` field embedded directly on `NodeOut` (matching
    Carl's shape) — kept as a Norman-only convenience endpoint, not
    something the real iOS app calls.
    """

    plant: NodeOut
    room: NodeOut | None  # the room-kind node in plant.room_id (None if no room node yet)


# --- History (mirror of hub's History schema) ---


class HistoryOut(BaseModel):
    node_id: str
    range: Literal["24h", "7d", "30d"]
    samples: list[Reading]


# --- Predictions ---


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    node_id: str
    ts: datetime
    kind: str
    payload: dict


# --- Ingest ---


class BatchAcceptedOut(BaseModel):
    rooms_seen: int
    nodes_seen: int
    samples_inserted: int
