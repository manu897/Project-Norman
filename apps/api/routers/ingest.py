"""Hub→Norman batch upload.

`POST /api/hubs/{hub_id}/batch` with `Authorization: Bearer <hub_api_token>`.
Idempotent on `(ts, node_id, metric)` so the hub can safely retry after
network blips.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Node, Reading
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
    """Ingest a hub batch. Upserts nodes, inserts long-format readings."""
    # Tag this hub as recently seen.
    hub.last_seen_at = datetime.now(timezone.utc)

    samples_inserted = 0
    for node in body.nodes:
        node_latest_ts: datetime | None = None
        battery_pct_seen: int | None = None
        for sample in node.samples:
            if node_latest_ts is None or sample.ts > node_latest_ts:
                node_latest_ts = sample.ts
                if sample.battery_pct is not None:
                    battery_pct_seen = sample.battery_pct

        # Upsert the node row itself.
        node_stmt = (
            pg_insert(Node)
            .values(
                id=node.id,
                hub_id=hub.id,
                mac=node.mac,
                name=node.name,
                battery_pct=battery_pct_seen,
                calibration=node.calibration.model_dump() if node.calibration else None,
                last_seen_at=node_latest_ts,
            )
            .on_conflict_do_update(
                index_elements=[Node.id],
                set_={
                    "mac": node.mac,
                    "name": node.name,
                    "hub_id": hub.id,
                    "battery_pct": battery_pct_seen,
                    "calibration": node.calibration.model_dump() if node.calibration else None,
                    "last_seen_at": node_latest_ts,
                },
            )
        )
        await session.execute(node_stmt)

        # Flatten + bulk-upsert readings in long format.
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
    return BatchAcceptedOut(nodes_seen=len(body.nodes), samples_inserted=samples_inserted)
