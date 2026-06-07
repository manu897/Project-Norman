"""Seed a demo user + hub (with API token) for local dev.

Run with: docker compose run --rm api python -m apps.api.seed

Writes the demo hub's plaintext API token to `.demo-hub-token` in the
container working directory — the fake-hub-post script reads it from there.
"""

import asyncio
import logging
import pathlib

from sqlalchemy import select

from apps.api.db import SessionLocal
from apps.api.models import Hub, User
from apps.api.security import generate_hub_token, hash_hub_token, hash_password

DEMO_EMAIL = "demo@norman.local"
DEMO_PASSWORD = "demodemo1"
DEMO_HUB_ID = "hub-001"
TOKEN_FILE = pathlib.Path(".demo-hub-token")

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
            plain_token = generate_hub_token()
            hub = Hub(
                id=DEMO_HUB_ID,
                owner_id=user.id,
                name="Demo Hub",
                location="lab",
                api_token_hash=hash_hub_token(plain_token),
            )
            session.add(hub)
            TOKEN_FILE.write_text(plain_token)
            log.info("created demo hub %s — token written to %s", DEMO_HUB_ID, TOKEN_FILE)
        else:
            log.info("demo hub %s already exists (token unchanged)", DEMO_HUB_ID)

        await session.commit()
    log.info("seed complete — login with %s / %s", DEMO_EMAIL, DEMO_PASSWORD)


if __name__ == "__main__":
    asyncio.run(main())
