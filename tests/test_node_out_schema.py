"""Contract test: Norman's NodeOut must match Carl's authoritative shape.

Source of truth: `Project-Carl/documents/api/openapi.yaml` (Node/RoomEnv
schemas) and `Project-Carl-IOS/CarlApp/Models/Plant.swift` (the actual Swift
decoder). If this test breaks, check those two files before changing the
assertions here — they're what decides the "right" shape, not this file.
"""

from datetime import datetime, timezone

from apps.api.schemas import NodeOut, RoomEnv
from packages.schemas.telemetry import Reading


def _node(**overrides) -> NodeOut:
    defaults = dict(
        id="aabbccddeeff",
        mac="AA:BB:CC:DD:EE:FF",
        name="Bedroom Monstera",
        node_type="plant",
        room_id="",
        hub_id="hub-001",
        species=None,
        online=True,
        last_seen=None,
        battery_pct=None,
        latest=None,
        calibration=None,
        room=None,
    )
    defaults.update(overrides)
    return NodeOut(**defaults)


def test_field_is_node_type_not_kind() -> None:
    """Carl-IOS decodes `node_type`; an old `kind` key would silently vanish."""
    dumped = _node().model_dump(mode="json")
    assert "node_type" in dumped
    assert "kind" not in dumped


def test_unassigned_room_id_is_empty_string_not_null() -> None:
    """CarlApp/Models/Plant.swift's `roomId: String` is non-optional."""
    dumped = _node(room_id="").model_dump(mode="json")
    assert dumped["room_id"] == ""
    assert dumped["room_id"] is not None


def test_room_is_embedded_on_the_node_not_a_separate_lookup() -> None:
    room = RoomEnv(
        source="room-1",
        ts=datetime(2026, 8, 25, tzinfo=timezone.utc),
        temperature_c=21.4,
        humidity_pct=55.0,
    )
    dumped = _node(room_id="living-room", room=room).model_dump(mode="json")
    assert dumped["room"]["source"] == "room-1"
    assert dumped["room"]["temperature_c"] == 21.4
    # RoomEnv field names must match Carl's exactly — Swift decodes these keys.
    assert set(dumped["room"]) == {
        "source", "ts", "temperature_c", "humidity_pct", "pressure_hpa", "illuminance_lux",
    }


def test_room_is_none_when_unassigned() -> None:
    assert _node(room_id="").model_dump(mode="json")["room"] is None


def test_latest_reading_serializes_with_carl_metric_names() -> None:
    reading = Reading(ts=datetime(2026, 8, 25, tzinfo=timezone.utc), soil_pct=42.2)
    dumped = _node(latest=reading).model_dump(mode="json")
    assert dumped["latest"]["soil_pct"] == 42.2
    assert dumped["latest"]["temperature_c"] is None  # nullable, not omitted
