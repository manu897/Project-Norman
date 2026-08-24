"""Tests for the MQTT NodeMessage contract — what Carl publishes on `carl/{site}/{node}`."""

import pytest
from pydantic import ValidationError

from packages.schemas.telemetry import KNOWN_METRICS, NodeMessage


# Mirrors firmware/hub/main/norman_uplink.c::publish_node() output exactly.
VALID_PAYLOAD = {
    "node": "aabbccddeeff",
    "mac": "AA:BB:CC:DD:EE:FF",
    "name": "Bedroom Monstera",
    "online": True,
    "soil_pct": 41.0,
    "temperature_c": 23.1,
    "humidity_pct": 58.0,
    "pressure_hpa": 1013.2,
    "illuminance_lux": 420.0,
    "battery_pct": 78,
}


def test_round_trip() -> None:
    m = NodeMessage.model_validate(VALID_PAYLOAD)
    assert m.node == "aabbccddeeff"
    assert m.mac == "AA:BB:CC:DD:EE:FF"
    assert m.online is True
    assert m.soil_pct == 41.0


def test_metric_pairs_returns_only_present_known_metrics() -> None:
    m = NodeMessage.model_validate(
        {"node": "n1", "mac": "AA:BB:CC:DD:EE:FF", "name": "x", "soil_pct": 41.0}
    )
    pairs = dict(m.metric_pairs())
    assert pairs == {"soil_pct": 41.0}
    assert all(metric in KNOWN_METRICS for metric in pairs)


def test_no_ts_field_present() -> None:
    """Carl's payload deliberately has no `ts` — Norman stamps receipt time."""
    assert "ts" not in NodeMessage.model_fields


def test_minimal_payload_with_just_identity() -> None:
    """Heartbeat (online status, no metrics) — should validate."""
    m = NodeMessage.model_validate(
        {"node": "n1", "mac": "AA:BB:CC:DD:EE:FF", "name": "x", "online": False}
    )
    assert m.online is False
    assert m.metric_pairs() == []


def test_online_defaults_to_true() -> None:
    """Carl always sends `online` but be lenient if it's missing."""
    m = NodeMessage.model_validate(
        {"node": "n1", "mac": "AA:BB:CC:DD:EE:FF", "name": "x"}
    )
    assert m.online is True


def test_missing_required_node_rejected() -> None:
    bad = {k: v for k, v in VALID_PAYLOAD.items() if k != "node"}
    with pytest.raises(ValidationError):
        NodeMessage.model_validate(bad)


def test_unknown_metric_ignored_not_rejected() -> None:
    """Forward-compat: Carl can add a metric before Norman documents it."""
    payload = {**VALID_PAYLOAD, "co2_ppm": 412}
    m = NodeMessage.model_validate(payload)
    assert m.soil_pct == 41.0  # known metrics still parse
