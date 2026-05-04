"""Seed a demo user, hub, and sensor for local dev.

Run with: docker compose run --rm api python -m apps.api.seed
"""

import asyncio
import logging

from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.models import Hub, Sensor, User
from apps.api.security import hash_password

DEMO_EMAIL = "demo@norman.local"
DEMO_PASSWORD = "demodemo1"
DEMO_HUB_ID = "hub-001"
DEMO_SENSOR_ID = "node-3"

log = logging.getLogger("seed")
logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")


async def main() -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD))
            session.add(user)
            await session.flush()
            log.info("created demo user %s", DEMO_EMAIL)
        else:
            log.info("demo user %s already exists", DEMO_EMAIL)

        hub = await session.get(Hub, DEMO_HUB_ID)
        if hub is None:
            hub = Hub(id=DEMO_HUB_ID, owner_id=user.id, name="Demo Hub", location="lab")
            session.add(hub)
            log.info("created demo hub %s", DEMO_HUB_ID)

        sensor = await session.get(Sensor, DEMO_SENSOR_ID)
        if sensor is None:
            session.add(Sensor(id=DEMO_SENSOR_ID, hub_id=DEMO_HUB_ID, label="BME680 #3"))
            log.info("created demo sensor %s", DEMO_SENSOR_ID)

        await session.commit()
    log.info("seed complete — login with %s / %s", DEMO_EMAIL, DEMO_PASSWORD)


if __name__ == "__main__":
    asyncio.run(main())
