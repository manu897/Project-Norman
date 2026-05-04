"""SQLAlchemy ORM models — used by api and ingest."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    String,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="hubs")
    sensors: Mapped[list["Sensor"]] = relationship(
        back_populates="hub", cascade="all, delete-orphan"
    )


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hub_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("hubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), default="bme680", nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hub: Mapped[Hub] = relationship(back_populates="sensors")


class Reading(Base):
    """Long-format time-series row. Hypertable on `ts` after migration."""

    __tablename__ = "readings"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    sensor_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hub_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("hubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB().with_variant(JSON, "sqlite"), nullable=False)
