"""Pydantic API request/response models (separate from ORM)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HubCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    location: str | None = None


class HubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: str | None
    created_at: datetime


class SensorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hub_id: str
    kind: str
    label: str | None
    last_seen_at: datetime | None


class ReadingOut(BaseModel):
    ts: datetime
    metric: str
    value: float


class LatestReadingOut(BaseModel):
    sensor_id: str
    metrics: dict[str, ReadingOut]


class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hub_id: str
    ts: datetime
    kind: str
    payload: dict
