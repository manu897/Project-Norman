"""Read-side endpoints that mirror the hub's `/api/nodes/*` surface.

These are what Carl-IOS hits when the phone is off home Wi-Fi.
Auth is the user JWT (multi-tenant). Shapes match `Project-Carl-IOS/api/openapi.yaml`.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Node, Reading, User
from apps.api.schemas import HistoryOut, NodeOut, Reading as ReadingSchema
from apps.api.security import current_user
from packages.schemas.telemetry import KNOWN_METRICS

router = APIRouter(prefix="/v1/nodes", tags=["nodes"])

_RANGE_TO_DELTA: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_RANGE_TO_BUCKET: dict[str, str] = {
    # downsample wider ranges to keep payload reasonable for the iOS app
    "24h": "5 minutes",
    "7d": "1 hour",
    "30d": "6 hours",
}


async def _ensure_owned_node(node_id: str, user: User, session: AsyncSession) -> Node:
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    hub = await session.get(Hub, node.hub_id)
    if hub is None or hub.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return node


def _build_reading(ts: datetime, metric_values: dict[str, float]) -> ReadingSchema:
    return ReadingSchema(ts=ts, **metric_values)


async def _latest_reading(node_id: str, session: AsyncSession) -> ReadingSchema | None:
    """Latest sample, assembled from the most-recent value per metric."""
    sub = (
        select(Reading.metric, func.max(Reading.ts).label("ts"))
        .where(Reading.node_id == node_id)
        .group_by(Reading.metric)
        .subquery()
    )
    stmt = select(Reading).join(
        sub, and_(Reading.metric == sub.c.metric, Reading.ts == sub.c.ts)
    ).where(Reading.node_id == node_id)
    rows = (await session.scalars(stmt)).all()
    if not rows:
        return None
    newest_ts = max(r.ts for r in rows)
    metric_values = {r.metric: r.value for r in rows if r.metric in KNOWN_METRICS}
    return _build_reading(newest_ts, metric_values)


def _is_online(node: Node, now: datetime) -> bool:
    """Online if seen recently. Default cutoff matches the iOS Calibration default."""
    cutoff_minutes = 30
    if isinstance(node.calibration, dict):
        cutoff_minutes = int(node.calibration.get("offline_after_minutes", cutoff_minutes))
    if node.last_seen_at is None:
        return False
    return (now - node.last_seen_at) <= timedelta(minutes=cutoff_minutes)


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[NodeOut]:
    """All nodes the user owns (across all their hubs)."""
    stmt = select(Node).join(Hub, Hub.id == Node.hub_id).where(Hub.owner_id == user.id)
    nodes = (await session.scalars(stmt)).all()
    now = datetime.now(timezone.utc)
    out: list[NodeOut] = []
    for node in nodes:
        latest = await _latest_reading(node.id, session)
        out.append(
            NodeOut(
                id=node.id,
                mac=node.mac,
                name=node.name,
                hub_id=node.hub_id,
                online=_is_online(node, now),
                last_seen=node.last_seen_at,
                battery_pct=node.battery_pct,
                latest=latest,
                calibration=node.calibration,
            )
        )
    return out


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(
    node_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NodeOut:
    node = await _ensure_owned_node(node_id, user, session)
    latest = await _latest_reading(node.id, session)
    return NodeOut(
        id=node.id,
        mac=node.mac,
        name=node.name,
        hub_id=node.hub_id,
        online=_is_online(node, datetime.now(timezone.utc)),
        last_seen=node.last_seen_at,
        battery_pct=node.battery_pct,
        latest=latest,
        calibration=node.calibration,
    )


@router.get("/{node_id}/history", response_model=HistoryOut)
async def get_node_history(
    node_id: str,
    range: Literal["24h", "7d", "30d"] = Query("24h"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryOut:
    await _ensure_owned_node(node_id, user, session)

    now = datetime.now(timezone.utc)
    from_ts = now - _RANGE_TO_DELTA[range]
    bucket = _RANGE_TO_BUCKET[range]

    sql = text(
        """
        SELECT time_bucket(:bucket, ts) AS ts, metric, avg(value) AS value
        FROM readings
        WHERE node_id = :node_id AND ts >= :from_ts AND ts <= :now
        GROUP BY 1, 2
        ORDER BY 1
        """
    )
    rows = (
        await session.execute(
            sql, {"bucket": bucket, "node_id": node_id, "from_ts": from_ts, "now": now}
        )
    ).all()

    # Group rows by bucketed ts → assemble per-ts Reading.
    by_ts: dict[datetime, dict[str, float]] = {}
    for r in rows:
        if r.metric not in KNOWN_METRICS:
            continue
        by_ts.setdefault(r.ts, {})[r.metric] = r.value

    samples = [_build_reading(ts, vals) for ts, vals in sorted(by_ts.items())]
    return HistoryOut(node_id=node_id, range=range, samples=samples)
