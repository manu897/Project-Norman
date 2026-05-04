"""Placeholder ML training pipeline.

Real model training waits until enough telemetry has accumulated. For now
this stub:
  - reads readings from Postgres
  - logs basic stats
  - writes a dummy model artifact to local disk (or GCS in prod)

Run with: python -m apps.ml.train
"""

import asyncio
import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.models import Reading

log = logging.getLogger("ml.train")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")

ARTIFACT_DIR = pathlib.Path("artifacts")


async def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    async with SessionLocal() as session:
        rows = (
            await session.scalars(select(Reading).where(Reading.ts >= cutoff))
        ).all()

    log.info("read %d readings since %s", len(rows), cutoff.isoformat())

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = ARTIFACT_DIR / "model.json"
    artifact.write_text(
        json.dumps(
            {
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "n_readings": len(rows),
                "model": "placeholder",
            }
        )
    )
    log.info("wrote placeholder model to %s", artifact)


if __name__ == "__main__":
    asyncio.run(main())
