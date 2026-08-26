"""MQTT ingest worker — Carl→Norman over MQTT (the primary ingest path).

Subscribes to `carl/+/+` (`carl/{site_id}/{node_id}`), validates each message
against `NodeMessage`, writes one row per present metric to `readings` with
`ts = now()`, and upserts the `nodes` row.

The HTTPS batch endpoint at `POST /v1/hubs/{id}/batch` is the alternate path
for richer payloads (rooms, kinds, calibration, historical samples). Both
land in the same tables.

Policy: messages from unknown `site_id` are DROPPED with a warning. The user
must register the hub on Norman first (`POST /v1/hubs`) — this gives Norman
ownership context the broker can't supply.
"""

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone

from aiomqtt import Client, MqttError
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api.config import get_settings
from apps.api.db import SessionLocal
from apps.api.models import Hub, Node, Reading
from packages.schemas.telemetry import NodeKind, NodeMessage

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("ingest")


def _parse_topic(topic: str) -> tuple[str, str] | None:
    """`carl/{site_id}/{node_id}` → (site_id, node_id), or None if malformed."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "carl":
        return None
    return parts[1], parts[2]


def _node_upsert_values(
    msg: NodeMessage, site_id: str, ts: datetime
) -> tuple[dict[str, object], dict[str, object]]:
    """(insert_values, update_values) for the node upsert.

    `node_type`/`room_id` are authoritative on every message when present —
    a node ingested before the hub started sending them self-heals on its
    very next publish, instead of staying wrong until someone hand-corrects
    Postgres. When a message omits the field (older firmware not yet
    updated), the update leaves whatever's already stored alone — that's
    why they're only added to `update_values` conditionally, never
    unconditionally.
    """
    insert_values: dict[str, object] = {
        "id": msg.node,
        "hub_id": site_id,
        "kind": msg.node_type.value if msg.node_type else NodeKind.plant.value,
        "room_id": msg.room_id,
        "mac": msg.mac,
        "name": msg.name,
        "battery_pct": msg.battery_pct,
        "last_seen_at": ts,
    }
    update_values: dict[str, object] = {
        "mac": msg.mac,
        "name": msg.name,
        "battery_pct": msg.battery_pct,
        "last_seen_at": ts,
    }
    if msg.node_type is not None:
        update_values["kind"] = msg.node_type.value
    if msg.room_id is not None:
        update_values["room_id"] = msg.room_id
    return insert_values, update_values


async def handle_message(raw: bytes, topic: str) -> None:
    parsed = _parse_topic(topic)
    if parsed is None:
        log.warning("dropping message on unexpected topic %s", topic)
        return
    site_id, topic_node_id = parsed

    try:
        data = json.loads(raw.decode("utf-8"))
        msg = NodeMessage.model_validate(data)
    except (ValueError, ValidationError) as exc:
        log.warning("dropping malformed message on %s: %s", topic, exc)
        return

    if msg.node != topic_node_id:
        log.warning(
            "topic node_id=%s does not match payload.node=%s on %s — dropping",
            topic_node_id, msg.node, topic,
        )
        return

    ts = datetime.now(timezone.utc)  # receipt time — Carl payload has no ts

    async with SessionLocal() as session:
        # Hub must exist. We do NOT auto-create — forces a clean ownership flow.
        hub = await session.get(Hub, site_id)
        if hub is None:
            log.warning(
                "dropping message from unknown hub site_id=%s — register it via POST /v1/hubs first",
                site_id,
            )
            return
        hub.last_seen_at = ts

        insert_values, update_values = _node_upsert_values(msg, site_id, ts)
        node_stmt = (
            pg_insert(Node)
            .values(**insert_values)
            .on_conflict_do_update(index_elements=[Node.id], set_=update_values)
        )
        await session.execute(node_stmt)

        rows = [
            {"ts": ts, "node_id": msg.node, "metric": metric, "value": value}
            for metric, value in msg.metric_pairs()
        ]
        if rows:
            readings_stmt = (
                pg_insert(Reading)
                .values(rows)
                .on_conflict_do_update(
                    index_elements=[Reading.ts, Reading.node_id, Reading.metric],
                    set_={"value": pg_insert(Reading).excluded.value},
                )
            )
            await session.execute(readings_stmt)

        await session.commit()

    log.info(
        "ingested %d metrics for site=%s node=%s (online=%s)",
        len(rows), site_id, msg.node, msg.online,
    )


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
