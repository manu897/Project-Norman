"""Hub→Norman batch upload.

`POST /v1/hubs/{hub_id}/batch` with `Authorization: Bearer <hub_api_token>`.
Idempotent on `(ts, node_id, metric)` so the hub can safely retry after
network blips.

End-state shape: hub uploads its rooms + every node (plant/room/camera) it knows
about. Plant nodes carry `room_id` and `species`. Camera images are NOT in this
payload — they stay on the hub.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Node, Reading, Room
from apps.api.schemas import BatchAcceptedOut
from apps.api.security import hub_from_token
from packages.schemas.telemetry import HubBatchUpload

router = APIRouter(prefix="/v1/hubs", tags=["ingest"])


@router.post(
    "/{hub_id}/batch",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BatchAcceptedOut,
)
async def upload_batch(
    hub_id: str,
    body: HubBatchUpload,
    hub: Hub = Depends(hub_from_token),
    session: AsyncSession = Depends(get_session),
) -> BatchAcceptedOut:
    """Ingest a hub batch. Upserts rooms + nodes, inserts long-format readings."""
    hub.last_seen_at = datetime.now(timezone.utc)

    # ---- Rooms ----
    for room in body.rooms:
        room_stmt = (
            pg_insert(Room)
            .values(id=room.id, hub_id=hub.id, name=room.name)
            .on_conflict_do_update(
                index_elements=[Room.id, Room.hub_id],
                set_={"name": room.name},
            )
        )
        await session.execute(room_stmt)

    # ---- Nodes + readings ----
    samples_inserted = 0
    for node in body.nodes:
        # Track latest timestamp + latest battery_pct seen in this batch.
        node_latest_ts: datetime | None = None
        battery_pct_seen: int | None = None
        for sample in node.samples:
            if node_latest_ts is None or sample.ts > node_latest_ts:
                node_latest_ts = sample.ts
                if sample.battery_pct is not None:
                    battery_pct_seen = sample.battery_pct

        node_values = {
            "id": node.id,
            "hub_id": hub.id,
            "kind": node.kind.value,
            "mac": node.mac,
            "name": node.name,
            "room_id": node.room_id,
            "species": node.species,
            "battery_pct": battery_pct_seen,
            "calibration": node.calibration.model_dump() if node.calibration else None,
            "last_seen_at": node_latest_ts,
        }
        node_stmt = (
            pg_insert(Node)
            .values(**node_values)
            .on_conflict_do_update(
                index_elements=[Node.id],
                set_={k: v for k, v in node_values.items() if k != "id"},
            )
        )
        await session.execute(node_stmt)

        rows: list[dict] = []
        for sample in node.samples:
            for ts, nid, metric, value in sample.to_long_rows(node.id):
                rows.append({"ts": ts, "node_id": nid, "metric": metric, "value": value})

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
            samples_inserted += len(rows)

    await session.commit()
    return BatchAcceptedOut(
        rooms_seen=len(body.rooms),
        nodes_seen=len(body.nodes),
        samples_inserted=samples_inserted,
    )
