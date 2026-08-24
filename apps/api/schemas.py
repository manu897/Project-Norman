"""Pydantic request/response models for the Norman REST API.

Reading/Node/Calibration/History shapes mirror `Project-Carl-IOS/api/openapi.yaml`
so the iOS app speaks one contract for both LAN-hub and cloud-Norman paths.
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


# --- Nodes (mirror of hub's Node schema, extended with kind/room_id/species) ---


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: NodeKind
    mac: str
    name: str
    hub_id: str
    room_id: str | None
    species: str | None
    online: bool
    last_seen: datetime | None
    battery_pct: int | None
    latest: Reading | None
    calibration: Calibration | None


class RoomDetailOut(RoomOut):
    """A room + its assigned nodes (room-kind + plants in it)."""

    nodes: list[NodeOut]


class SnapshotOut(BaseModel):
    """Plant's joined view: plant probe readings + assigned room's ambient."""

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
