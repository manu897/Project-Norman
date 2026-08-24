import logging

from fastapi import FastAPI

from apps.api.config import get_settings
from apps.api.routers import auth, hubs, ingest, nodes, rooms

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

app = FastAPI(
    title="Norman API",
    version="0.2.0",
    description=(
        "Project Norman REST API. Mirrors the Carl hub HTTP contract "
        "(`Project-Carl-IOS/api/openapi.yaml`) on the read side so the iOS app "
        "uses one shape for both LAN-hub and cloud-Norman paths. Ingest is "
        "HTTPS batch upload from the hub, authenticated with a per-hub bearer token. "
        "Three node kinds: plant / room / camera; predictions are per-plant-node."
    ),
)

app.include_router(auth.router)
app.include_router(hubs.router)
app.include_router(rooms.router)
app.include_router(nodes.router)
app.include_router(ingest.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
