"""Pure-Python tests for the Carl-hub → Norman batch contract. No DB required."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.schemas.telemetry import (
    KNOWN_METRICS,
    Calibration,
    HubBatchUpload,
    NodeBatch,
    Reading,
)

VALID_BATCH = {
    "hub_version": "0.1.0",
    "generated_at": "2026-05-04T18:00:00Z",
    "nodes": [
        {
            "id": "aabbccddeeff",
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Bedroom Monstera",
            "calibration": {
                "soil_dry_pct": 25.0,
                "soil_wet_pct": 65.0,
                "battery_low_pct": 15,
                "offline_after_minutes": 30,
            },
            "samples": [
                {
                    "ts": "2026-05-04T17:55:00Z",
                    "temperature_c": 24.3,
                    "humidity_pct": 61.2,
                    "pressure_hpa": 1013.2,
                    "soil_pct": 41.0,
                    "illuminance_lux": 320.0,
                    "battery_pct": 78,
                }
            ],
        }
    ],
}


def test_round_trip() -> None:
    batch = HubBatchUpload.model_validate(VALID_BATCH)
    assert batch.hub_version == "0.1.0"
    assert batch.generated_at == datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc)
    assert len(batch.nodes) == 1
    node = batch.nodes[0]
    assert node.mac == "AA:BB:CC:DD:EE:FF"
    assert isinstance(node.calibration, Calibration)
    assert node.samples[0].soil_pct == 41.0


def test_reading_flattens_only_non_null_known_metrics() -> None:
    r = Reading(
        ts=datetime(2026, 5, 4, 18, 0, tzinfo=timezone.utc),
        temperature_c=24.3,
        humidity_pct=61.2,
        # all other metrics left None
    )
    rows = r.to_long_rows("node-1")
    metrics = {row[2] for row in rows}
    assert metrics == {"temperature_c", "humidity_pct"}
    assert all(m in KNOWN_METRICS for m in metrics)


def test_unknown_metric_in_reading_is_ignored_not_rejected() -> None:
    """Forward-compat: hub firmware can ship a new metric before Norman knows about it."""
    r = Reading.model_validate(
        {
            "ts": "2026-05-04T18:00:00Z",
            "temperature_c": 24.3,
            "co2_ppm": 412,  # not yet in KNOWN_METRICS
        }
    )
    assert r.temperature_c == 24.3
    # not on the model — but the parse succeeded


def test_batch_extra_top_level_field_rejected() -> None:
    """Top-level extras are forbidden — catches typos like `node` vs `nodes`."""
    with pytest.raises(ValidationError):
        HubBatchUpload.model_validate({**VALID_BATCH, "node": []})


def test_node_extra_field_rejected() -> None:
    """Node-level extras forbidden too."""
    bad = {**VALID_BATCH, "nodes": [{**VALID_BATCH["nodes"][0], "weird": 1}]}
    with pytest.raises(ValidationError):
        HubBatchUpload.model_validate(bad)


def test_missing_required_node_field_rejected() -> None:
    bad_node = {k: v for k, v in VALID_BATCH["nodes"][0].items() if k != "mac"}
    with pytest.raises(ValidationError):
        NodeBatch.model_validate(bad_node)


def test_empty_samples_is_valid() -> None:
    """A batch with a node that reports no new samples is OK — used as a heartbeat."""
    raw = {**VALID_BATCH, "nodes": [{**VALID_BATCH["nodes"][0], "samples": []}]}
    batch = HubBatchUpload.model_validate(raw)
    assert batch.nodes[0].samples == []
