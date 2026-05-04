"""Norman ingest worker.

Subscribes to MQTT, validates each message against the telemetry contract,
upserts the sensor row, and bulk-inserts long-format readings.
"""

import asyncio
import json
import logging
import signal

from aiomqtt import Client, MqttError
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api.config import get_settings
from apps.api.db import SessionLocal
from apps.api.models import Reading, Sensor
from packages.schemas.telemetry import TelemetryPayload

settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingest")


async def handle_message(raw: bytes, topic: str) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
        payload = TelemetryPayload.model_validate(data)
    except (ValueError, ValidationError) as exc:
        log.warning("dropping malformed message on %s: %s", topic, exc)
        return

    rows = [
        {"ts": ts, "sensor_id": sid, "metric": m, "value": v}
        for ts, sid, m, v in payload.flatten()
    ]
    if not rows:
        return

    async with SessionLocal() as session:
        sensor_stmt = (
            pg_insert(Sensor)
            .values(id=payload.sensor_id, hub_id=payload.hub_id, last_seen_at=payload.ts)
            .on_conflict_do_update(
                index_elements=[Sensor.id],
                set_={"last_seen_at": payload.ts, "hub_id": payload.hub_id},
            )
        )
        await session.execute(sensor_stmt)

        readings_stmt = (
            pg_insert(Reading)
            .values(rows)
            .on_conflict_do_update(
                index_elements=[Reading.ts, Reading.sensor_id, Reading.metric],
                set_={"value": pg_insert(Reading).excluded.value},
            )
        )
        await session.execute(readings_stmt)
        await session.commit()

    log.info("ingested %d readings for sensor=%s hub=%s", len(rows), payload.sensor_id, payload.hub_id)


async def run() -> None:
    stop = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    while not stop.is_set():
        try:
            log.info("connecting to mqtt %s:%s", settings.MQTT_HOST, settings.MQTT_PORT)
            async with Client(
                hostname=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                username=settings.MQTT_USERNAME or None,
                password=settings.MQTT_PASSWORD or None,
            ) as client:
                await client.subscribe(settings.MQTT_TOPIC, qos=1)
                log.info("subscribed to %s", settings.MQTT_TOPIC)
                async for msg in client.messages:
                    if stop.is_set():
                        break
                    await handle_message(msg.payload, str(msg.topic))
        except MqttError as exc:
            log.warning("mqtt error: %s — reconnecting in 5s", exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(run())
