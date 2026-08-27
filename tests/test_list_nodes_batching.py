"""Tests for list_nodes' batched query path — the N+1 fix.

Measured live in production: GET /v1/nodes took ~500-650ms more than pure
GCP-network-distance explained, for just 2 nodes. Root cause: the old
per-node loop called `_to_node_out`, which did its own latest-reading query,
plus (for plant nodes) a room lookup and the room's own latest-reading query
— up to 3 sequential DB round-trips per node, so up to 3N for N nodes.

`_batch_room_nodes` / `_batch_latest_readings` / `_assemble_node_out`
replace that with a fixed 3 queries for the whole list. `_match_room_nodes`
and `_assemble_node_out` need no DB at all, so they're tested directly here;
the two `_batch_*` functions are thin query-shaping wrappers around them and
aren't independently exercised without a live database (consistent with
this repo's existing pure-Python test style).
"""

from datetime import datetime, timezone

from apps.api.models import Node
from apps.api.routers.nodes import _assemble_node_out, _match_room_nodes
from apps.api.schemas import Reading


def _node(id: str, kind: str, hub_id: str = "hub-1", room_id: str | None = None, **kw) -> Node:
    return Node(
        id=id, hub_id=hub_id, kind=kind, mac="AA:BB:CC:DD:EE:FF", name=id,
        room_id=room_id, species=None, battery_pct=kw.get("battery_pct"),
        calibration=None, last_seen_at=kw.get("last_seen_at"),
    )


# --- _match_room_nodes ---


def test_match_by_room_nodes_own_room_id() -> None:
    plant = _node("p1", "plant", room_id="living-room")
    room = _node("r1", "room", room_id="living-room")
    matches = _match_room_nodes([plant], [room])
    assert matches == {"p1": room}


def test_match_by_room_node_id_equals_plant_room_id() -> None:
    """The convention Carl's hub actually uses — no separate room_id on the room node itself."""
    plant = _node("p1", "plant", room_id="room-bedroom")
    room = _node("room-bedroom", "room", room_id=None)
    matches = _match_room_nodes([plant], [room])
    assert matches == {"p1": room}


def test_plant_with_no_room_id_has_no_match() -> None:
    plant = _node("p1", "plant", room_id=None)
    room = _node("r1", "room", room_id="living-room")
    assert _match_room_nodes([plant], [room]) == {}


def test_room_ids_scoped_per_hub_no_cross_hub_match() -> None:
    """Same room_id string under a different hub must not match — hub_id is part of the key."""
    plant = _node("p1", "plant", hub_id="hub-A", room_id="living-room")
    room = _node("r1", "room", hub_id="hub-B", room_id="living-room")
    assert _match_room_nodes([plant], [room]) == {}


def test_multiple_plants_batch_correctly() -> None:
    """This is the actual point of batching — many plants resolved in one pass."""
    room1 = _node("r1", "room", room_id="living-room")
    room2 = _node("r2", "room", room_id="bedroom")
    plants = [
        _node("p1", "plant", room_id="living-room"),
        _node("p2", "plant", room_id="bedroom"),
        _node("p3", "plant", room_id=None),  # unassigned — no match expected
    ]
    matches = _match_room_nodes(plants, [room1, room2])
    assert matches == {"p1": room1, "p2": room2}


# --- _assemble_node_out ---


def test_assemble_node_out_embeds_room_when_matched_and_readable() -> None:
    now = datetime.now(timezone.utc)
    plant = _node("p1", "plant", room_id="living-room", last_seen_at=now)
    room_node = _node("r1", "room")
    room_reading = Reading(ts=now, temperature_c=21.4)

    out = _assemble_node_out(
        plant, now,
        latest_by_id={"r1": room_reading},
        room_by_plant_id={"p1": room_node},
    )
    assert out.room is not None
    assert out.room.source == "r1"
    assert out.room.temperature_c == 21.4


def test_assemble_node_out_room_none_when_room_has_no_reading_yet() -> None:
    now = datetime.now(timezone.utc)
    plant = _node("p1", "plant", room_id="living-room", last_seen_at=now)
    room_node = _node("r1", "room")

    out = _assemble_node_out(
        plant, now, latest_by_id={}, room_by_plant_id={"p1": room_node},
    )
    assert out.room is None


def test_assemble_node_out_room_node_never_gets_a_room_embedded_on_itself() -> None:
    """Mirrors _room_env_for's existing rule — only plant nodes get `room` grafted on."""
    now = datetime.now(timezone.utc)
    room = _node("r1", "room", last_seen_at=now)
    out = _assemble_node_out(
        room, now,
        latest_by_id={"r1": Reading(ts=now, temperature_c=21.4)},
        room_by_plant_id={},
    )
    assert out.room is None


def test_assemble_node_out_uses_precomputed_latest_reading() -> None:
    now = datetime.now(timezone.utc)
    plant = _node("p1", "plant", last_seen_at=now)
    reading = Reading(ts=now, soil_pct=42.2)
    out = _assemble_node_out(plant, now, latest_by_id={"p1": reading}, room_by_plant_id={})
    assert out.latest is reading
