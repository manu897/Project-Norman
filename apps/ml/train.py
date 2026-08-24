"""Per-plant ML pipeline (stubbed).

Real model training waits until enough telemetry has accumulated. For now
this stub:
  - finds every plant node + its assigned room
  - reads joined readings (plant probe + room ambient) for the last 7 days
  - writes a placeholder `{health_score, days_until_water_needed, confidence}`
    prediction per plant
  - dumps a marker artifact to local disk (or GCS in prod)

Schedule this as a nightly job: `docker compose run --rm api python -m apps.ml.train`.
"""

import asyncio
import json
import logging
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.models import Node, Prediction, Reading
from packages.schemas.telemetry import KNOWN_METRICS, NodeKind

log = logging.getLogger("ml.train")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")

ARTIFACT_DIR = pathlib.Path("artifacts")
LOOKBACK = timedelta(days=7)


async def _plant_window(node: Node, since: datetime) -> dict[str, list[float]]:
    """Per-metric list of recent values for a plant + (if assigned) its room."""
    node_ids = [node.id]
    if node.room_id:
        node_ids.append(node.room_id)

    async with SessionLocal() as session:
        stmt = select(Reading).where(Reading.node_id.in_(node_ids), Reading.ts >= since)
        rows = (await session.scalars(stmt)).all()

    series: dict[str, list[float]] = {m: [] for m in KNOWN_METRICS}
    for r in rows:
        if r.metric in series:
            series[r.metric].append(r.value)
    return series


def _placeholder_prediction(series: dict[str, list[float]]) -> dict:
    """Stand-in until a real model lands. Naive heuristics over the soil reading."""
    soil = series.get("soil_pct") or []
    if not soil:
        return {
            "health_score": None,
            "days_until_water_needed": None,
            "confidence": 0.0,
            "note": "no soil data — using placeholder",
        }
    latest_soil = soil[-1]
    # Linear-ish: 65% wet → ~5 days; 25% dry → 0 days.
    days = max(0, round((latest_soil - 25) / 8))
    health = max(0.0, min(1.0, latest_soil / 100))
    return {
        "health_score": round(health, 2),
        "days_until_water_needed": days,
        "confidence": 0.1,  # this is a heuristic, not a model
        "note": "placeholder heuristic — replace with trained model",
    }


async def main() -> None:
    since = datetime.now(timezone.utc) - LOOKBACK

    async with SessionLocal() as session:
        plants_stmt = select(Node).where(Node.kind == NodeKind.plant.value)
        plants = (await session.scalars(plants_stmt)).all()

    log.info("training for %d plant nodes (lookback=%s)", len(plants), LOOKBACK)

    written = 0
    for plant in plants:
        series = await _plant_window(plant, since)
        payload = _placeholder_prediction(series)

        async with SessionLocal() as session:
            session.add(
                Prediction(
                    id=uuid.uuid4(),
                    node_id=plant.id,
                    ts=datetime.now(timezone.utc),
                    kind="health_v0",
                    payload=payload,
                )
            )
            await session.commit()
            written += 1

    log.info("wrote %d prediction rows", written)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "last_run.json").write_text(
        json.dumps(
            {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_plants": len(plants),
                "model": "placeholder_v0",
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
