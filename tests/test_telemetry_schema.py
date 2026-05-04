"""Pure-Python tests for the Carl→Norman contract. No DB or broker required."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.schemas.telemetry import KNOWN_METRICS, TelemetryPayload


def test_round_trip() -> None:
    raw = {
        "ts": "2026-04-30T18:30:00Z",
        "hub_id": "hub-001",
        "sensor_id": "node-3",
        "metrics": {
            "temperature_c": 24.3,
            "humidity_pct": 61.2,
            "pressure_hpa": 1013.2,
            "voc_index": 145,
            "battery_v": 3.71,
            "rssi_dbm": -67,
        },
    }
    p = TelemetryPayload.model_validate(raw)
    assert p.hub_id == "hub-001"
    assert p.sensor_id == "node-3"
    assert p.ts == datetime(2026, 4, 30, 18, 30, tzinfo=timezone.utc)
    assert set(p.metrics).issubset(set(KNOWN_METRICS))


def test_flatten_yields_one_row_per_metric() -> None:
    p = TelemetryPayload(
        ts=datetime(2026, 4, 30, 18, 30, tzinfo=timezone.utc),
        hub_id="hub-001",
        sensor_id="node-3",
        metrics={"temperature_c": 24.3, "humidity_pct": 61.2},
    )
    flat = p.flatten()
    assert len(flat) == 2
    metrics = {row[2] for row in flat}
    assert metrics == {"temperature_c", "humidity_pct"}


def test_unknown_metric_accepted() -> None:
    """Forward-compat: Carl can publish a new metric before Norman documents it."""
    p = TelemetryPayload(
        ts=datetime(2026, 4, 30, 18, 30, tzinfo=timezone.utc),
        hub_id="hub-001",
        sensor_id="node-3",
        metrics={"soil_moisture_pct": 41.0},
    )
    assert p.metrics["soil_moisture_pct"] == 41.0


def test_extra_top_level_field_rejected() -> None:
    """Top-level extras are forbidden — catches typos like `metric` vs `metrics`."""
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate(
            {
                "ts": "2026-04-30T18:30:00Z",
                "hub_id": "hub-001",
                "sensor_id": "node-3",
                "metrics": {"temperature_c": 24.3},
                "extra": "nope",
            }
        )


def test_missing_hub_id_rejected() -> None:
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate(
            {
                "ts": "2026-04-30T18:30:00Z",
                "sensor_id": "node-3",
                "metrics": {"temperature_c": 24.3},
            }
        )
