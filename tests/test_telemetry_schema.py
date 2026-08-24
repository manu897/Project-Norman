"""Pure-Python tests for the Carl-hub → Norman batch contract. No DB required."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.schemas.telemetry import (
    KNOWN_METRICS,
    Calibration,
    HubBatchUpload,
    NodeBatch,
    NodeKind,
    Reading,
)

VALID_BATCH = {
    "hub_version": "0.2.0",
    "generated_at": "2026-06-12T18:00:00Z",
    "rooms": [{"id": "room-bedroom", "name": "Bedroom"}],
    "nodes": [
        {
            "id": "room-bedroom",
            "kind": "room",
            "mac": "11:22:33:44:55:66",
            "name": "Bedroom Thingy",
            "samples": [
                {
                    "ts": "2026-06-12T17:55:00Z",
                    "temperature_c": 23.1,
                    "humidity_pct": 58.0,
                    "pressure_hpa": 1013.2,
                    "illuminance_lux": 420.0,
                }
            ],
        },
        {
            "id": "aabbccddeeff",
            "kind": "plant",
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Bedroom Monstera",
            "room_id": "room-bedroom",
            "species": "monstera_deliciosa",
            "calibration": {
                "soil_dry_pct": 25.0,
                "soil_wet_pct": 65.0,
                "battery_low_pct": 15,
                "offline_after_minutes": 30,
            },
            "samples": [
                {"ts": "2026-06-12T17:55:00Z", "soil_pct": 41.0, "battery_pct": 78}
            ],
        },
    ],
}


def test_round_trip() -> None:
    batch = HubBatchUpload.model_validate(VALID_BATCH)
    assert batch.hub_version == "0.2.0"
    assert batch.generated_at == datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    assert len(batch.rooms) == 1 and batch.rooms[0].name == "Bedroom"
    assert {n.kind for n in batch.nodes} == {NodeKind.room, NodeKind.plant}
    plant = next(n for n in batch.nodes if n.kind == NodeKind.plant)
    assert plant.room_id == "room-bedroom"
    assert plant.species == "monstera_deliciosa"
    assert isinstance(plant.calibration, Calibration)


def test_plant_kind_is_default_when_omitted() -> None:
    raw = {
        "id": "x", "mac": "AA:BB:CC:DD:EE:FF", "name": "n",
        "samples": [],
    }
    n = NodeBatch.model_validate(raw)
    assert n.kind == NodeKind.plant


def test_reading_flattens_only_non_null_known_metrics() -> None:
    r = Reading(
        ts=datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc),
        temperature_c=24.3,
        soil_pct=41.0,
    )
    rows = r.to_long_rows("node-1")
    metrics = {row[2] for row in rows}
    assert metrics == {"temperature_c", "soil_pct"}
    assert all(m in KNOWN_METRICS for m in metrics)


def test_unknown_metric_in_reading_is_ignored_not_rejected() -> None:
    """Forward-compat: hub firmware can ship a new metric before Norman knows about it."""
    r = Reading.model_validate(
        {"ts": "2026-06-12T18:00:00Z", "soil_pct": 41.0, "co2_ppm": 412}
    )
    assert r.soil_pct == 41.0


def test_batch_extra_top_level_field_rejected() -> None:
    with pytest.raises(ValidationError):
        HubBatchUpload.model_validate({**VALID_BATCH, "extras": []})


def test_node_extra_field_rejected() -> None:
    bad = {**VALID_BATCH, "nodes": [{**VALID_BATCH["nodes"][0], "weird": 1}]}
    with pytest.raises(ValidationError):
        HubBatchUpload.model_validate(bad)


def test_unknown_kind_rejected() -> None:
    bad = {**VALID_BATCH, "nodes": [{**VALID_BATCH["nodes"][0], "kind": "bogus"}]}
    with pytest.raises(ValidationError):
        HubBatchUpload.model_validate(bad)


def test_camera_kind_with_battery_only_is_valid() -> None:
    raw = {
        **VALID_BATCH,
        "nodes": [
            {
                "id": "cam-1",
                "kind": "camera",
                "mac": "AA:BB:CC:DD:EE:01",
                "name": "Window Cam",
                "samples": [{"ts": "2026-06-12T17:55:00Z", "battery_pct": 100}],
            }
        ],
    }
    batch = HubBatchUpload.model_validate(raw)
    assert batch.nodes[0].kind == NodeKind.camera


def test_empty_rooms_and_nodes_is_valid() -> None:
    """A heartbeat batch with no new data is OK — keeps `hubs.last_seen_at` fresh."""
    raw = {
        "hub_version": "0.2.0",
        "generated_at": "2026-06-12T18:00:00Z",
        "rooms": [],
        "nodes": [],
    }
    batch = HubBatchUpload.model_validate(raw)
    assert batch.nodes == [] and batch.rooms == []
