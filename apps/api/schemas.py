"""Pydantic request/response models for the Norman REST API.

Reading/Node/Calibration/History shapes mirror `Project-Carl-IOS/api/openapi.yaml`
so the iOS app speaks one contract for both LAN-hub and cloud-Norman paths.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from packages.schemas.telemetry import Calibration, HubBatchUpload, Reading

# Re-export shared schemas so router files can import everything from one place.
__all__ = [
    "RegisterRequest",
    "TokenResponse",
    "HubCreate",
    "HubOut",
    "HubCreateOut",
    "NodeOut",
    "HistoryOut",
    "PredictionOut",
    "BatchAcceptedOut",
    "Reading",
    "Calibration",
    "HubBatchUpload",
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


# --- Nodes (mirror of hub's Node schema) ---


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mac: str
    name: str
    hub_id: str
    online: bool
    last_seen: datetime | None
    battery_pct: int | None
    latest: Reading | None
    calibration: Calibration | None


# --- History (mirror of hub's History schema) ---


class HistoryOut(BaseModel):
    node_id: str
    range: Literal["24h", "7d", "30d"]
    samples: list[Reading]


# --- Predictions ---


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hub_id: str
    ts: datetime
    kind: str
    payload: dict


# --- Ingest ---


class BatchAcceptedOut(BaseModel):
    nodes_seen: int
    samples_inserted: int
