"""Regression test for a real production bug in `GET /v1/nodes/{id}/history`.

Root cause: `get_node_history`'s raw SQL averages `readings.value` (a plain
float column) per downsample bucket. `Reading.battery_pct` is `int | None`,
and Pydantic v2 rejects a float with a nonzero fractional part outright —
so any bucket containing more than one distinct `battery_pct` row (the
normal case for a hub reporting more than once per bucket — confirmed live
in production: every single 5-minute bucket for a real node had a
fractional average) crashed the whole endpoint with an unhandled
ValidationError -> bare 500.

Fix: `_coerce_aggregated_value` rounds `battery_pct` specifically before it
reaches `Reading`; every other metric is a legitimate float and passes
through unchanged.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from apps.api.routers.nodes import _build_reading, _coerce_aggregated_value


def test_raw_fractional_battery_pct_is_rejected_by_reading() -> None:
    """Documents the crash this test suite guards against — this is exactly
    what SQL avg() produces when a bucket holds >1 distinct raw value."""
    with pytest.raises(ValidationError):
        _build_reading(datetime.now(timezone.utc), {"battery_pct": 86.5})


def test_coerce_aggregated_value_rounds_battery_pct() -> None:
    assert _coerce_aggregated_value("battery_pct", 86.5) == 86
    assert _coerce_aggregated_value("battery_pct", 64.8) == 65  # matches live prod data
    assert isinstance(_coerce_aggregated_value("battery_pct", 86.5), int)


def test_coerce_aggregated_value_leaves_other_metrics_untouched() -> None:
    """temperature_c etc. are legitimately float — must not be rounded."""
    assert _coerce_aggregated_value("temperature_c", 23.456) == 23.456
    assert _coerce_aggregated_value("soil_pct", 41.2) == 41.2


def test_history_pipeline_survives_a_bucket_with_multiple_battery_readings() -> None:
    """End-to-end through the same two calls get_node_history makes: coerce,
    then build the Reading. This is the exact fix — without it, this test
    fails with the ValidationError reproduced above."""
    ts = datetime.now(timezone.utc)
    raw_avg = 86.5  # avg() over e.g. two raw rows: 87 and 86

    coerced = _coerce_aggregated_value("battery_pct", raw_avg)
    reading = _build_reading(ts, {"battery_pct": coerced})

    assert reading.battery_pct == 86
