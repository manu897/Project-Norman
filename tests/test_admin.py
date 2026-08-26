"""Tests for the superuser-only /v1/admin/* gate and response shapes.

No DB fixtures — `current_superuser` only inspects the `User` object FastAPI
already resolved via `current_user`, so a plain in-memory `User` is enough to
exercise the gate. Matches this repo's existing pure-Python test style (see
test_node_out_schema.py).
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from apps.api.models import User
from apps.api.schemas import AdminNodeOut, NodeOut, RoomEnv
from apps.api.security import current_superuser


def _user(*, is_superuser: bool) -> User:
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="x",
        is_superuser=is_superuser,
        created_at=datetime.now(timezone.utc),
    )


async def test_current_superuser_rejects_normal_account() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await current_superuser(_user(is_superuser=False))
    assert exc_info.value.status_code == 403


async def test_current_superuser_passes_through_admin_account() -> None:
    admin = _user(is_superuser=True)
    result = await current_superuser(admin)
    assert result is admin


def test_admin_node_out_reconstructs_from_node_out_with_owner_email() -> None:
    """AdminNodeOut = NodeOut + owner_email. Verifies the admin router's
    `AdminNodeOut(**base.model_dump(), owner_email=...)` pattern round-trips
    nested fields (room, latest, calibration) correctly, not just flat ones."""
    base = NodeOut(
        id="n1",
        mac="AA:BB:CC:DD:EE:FF",
        name="Test Room",
        node_type="room",
        room_id="",
        hub_id="hub-x",
        species=None,
        online=True,
        last_seen=datetime.now(timezone.utc),
        battery_pct=50,
        latest=None,
        calibration=None,
        room=RoomEnv(source="r1", ts=datetime.now(timezone.utc), temperature_c=22.0),
    )
    admin_out = AdminNodeOut(**base.model_dump(), owner_email="owner@example.com")

    assert admin_out.owner_email == "owner@example.com"
    assert admin_out.node_type == base.node_type
    assert admin_out.room is not None
    assert admin_out.room.temperature_c == 22.0
