import logging

from fastapi import FastAPI

from apps.api.config import get_settings
from apps.api.routers import auth, hubs, predictions, sensors

settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Norman API",
    version="0.1.0",
    description="Project Norman REST API for the Carl-IOS app and other clients.",
)

app.include_router(auth.router)
app.include_router(hubs.router)
app.include_router(sensors.router)
app.include_router(predictions.router)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
