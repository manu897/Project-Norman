"""SQLAlchemy ORM models for the Norman API.

End-state shape (aimed at Carl-fully-shipped):
  users → hubs → rooms (hub-scoped)
                 nodes (kind: plant | room | camera; plants reference a room)
  readings: long-format (ts, node_id, metric, value), hypertable on ts
  predictions: per-plant-node ML output
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Sees every hub/node/user across the whole deployment via /v1/admin/*,
    # regardless of ownership. Never settable through the API — flip it
    # directly in Postgres (`UPDATE users SET is_superuser = true WHERE
    # email = '...'`). Deliberately no self-service promotion path.
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hubs: Mapped[list["Hub"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Hub(Base):
    __tablename__ = "hubs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    api_token_hash: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="hubs")
    rooms: Mapped[list["Room"]] = relationship(
        back_populates="hub", cascade="all, delete-orphan"
    )
    nodes: Mapped[list["Node"]] = relationship(
        back_populates="hub", cascade="all, delete-orphan"
    )


class Room(Base):
    """Physical room within a hub. Hub-scoped id; (hub_id, id) is globally unique."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hub_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("hubs.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hub: Mapped[Hub] = relationship(back_populates="rooms")


class Node(Base):
    """Sensor node. `kind` discriminates plant vs room vs camera."""

    __tablename__ = "nodes"
    __table_args__ = (
        # Foreign key to (rooms.id, rooms.hub_id) requires the composite — see migration.
        UniqueConstraint("id", "hub_id", name="uq_nodes_id_hub"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hub_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("hubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="plant")
    mac: Mapped[str] = mapped_column(String(17), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Plant-only assignment (NULL for room/camera). Loosely linked: no DB-level
    # FK because rooms.id is composite (id, hub_id); we enforce in app code.
    room_id: Mapped[str | None] = mapped_column(String(64))
    species: Mapped[str | None] = mapped_column(String(64))
    battery_pct: Mapped[int | None] = mapped_column(Integer)
    calibration: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON, "sqlite"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hub: Mapped[Hub] = relationship(back_populates="nodes")


class Reading(Base):
    """Long-format time-series row. Hypertable on `ts` after migration."""

    __tablename__ = "readings"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class Prediction(Base):
    """Per-plant-node ML output."""

    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
