"""Regression test for a real production misclassification bug.

`node-BEC8` (a real Thingy:53 room sensor) was permanently stuck as
`kind='plant'` because Carl's MQTT wire format never included node_type at
all — the hub's `carl_node_snapshot_t` didn't carry it — so ingest hardcoded
every node to `plant` on first insert with no way to ever correct it short
of a manual `UPDATE nodes SET kind=...` in Postgres.

Carl's firmware now sends `node_type`/`room_id` when present. This tests
that ingest treats them as authoritative on *every* message — including
self-healing a node that was ingested wrong before the firmware update —
while never clobbering existing data when an older/partial message omits
the field.
"""

from datetime import datetime, timezone

from apps.ingest.main import _node_upsert_values
from packages.schemas.telemetry import NodeKind, NodeMessage


def _msg(**overrides) -> NodeMessage:
    defaults = dict(node="node-BEC8", mac="D1:5C:BC:68:BE:C8", name="node-BEC8")
    defaults.update(overrides)
    return NodeMessage.model_validate(defaults)


def test_first_insert_defaults_to_plant_when_node_type_absent() -> None:
    """Matches the historical behavior — old firmware, no node_type sent."""
    insert, _ = _node_upsert_values(_msg(), "hub-002", datetime.now(timezone.utc))
    assert insert["kind"] == NodeKind.plant.value


def test_first_insert_uses_node_type_when_present() -> None:
    insert, _ = _node_upsert_values(
        _msg(node_type="room"), "hub-002", datetime.now(timezone.utc)
    )
    assert insert["kind"] == NodeKind.room.value


def test_update_self_heals_kind_when_node_type_present() -> None:
    """This is the actual fix: a node stuck wrong from before the firmware
    update corrects itself on its very next publish, no manual DB fix needed."""
    _, update = _node_upsert_values(
        _msg(node_type="room"), "hub-002", datetime.now(timezone.utc)
    )
    assert update["kind"] == NodeKind.room.value


def test_update_leaves_kind_alone_when_node_type_absent() -> None:
    """Older/partial firmware that hasn't sent node_type yet must not
    clobber a kind that a newer message (or a manual correction) already set."""
    _, update = _node_upsert_values(_msg(), "hub-002", datetime.now(timezone.utc))
    assert "kind" not in update


def test_update_self_heals_room_id_when_present_but_leaves_alone_when_absent() -> None:
    _, update_with = _node_upsert_values(
        _msg(node_type="plant", room_id="living-room"),
        "hub-002",
        datetime.now(timezone.utc),
    )
    assert update_with["room_id"] == "living-room"

    _, update_without = _node_upsert_values(_msg(), "hub-002", datetime.now(timezone.utc))
    assert "room_id" not in update_without


def test_mac_name_battery_are_always_refreshed_regardless_of_node_type() -> None:
    """The pre-existing behavior for these fields must be untouched by this change."""
    _, update = _node_upsert_values(
        _msg(mac="AA:BB:CC:DD:EE:FF", name="Renamed", battery_pct=42),
        "hub-002",
        datetime.now(timezone.utc),
    )
    assert update["mac"] == "AA:BB:CC:DD:EE:FF"
    assert update["name"] == "Renamed"
    assert update["battery_pct"] == 42
