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
from apps.api.models import Hub, Node, Prediction, Reading, User
from apps.api.schemas import (
    HistoryOut,
    NodeOut,
    PredictionOut,
    Reading as ReadingSchema,
    RoomEnv,
    SnapshotOut,
)
from apps.api.security import current_user
from packages.schemas.telemetry import KNOWN_METRICS, NodeKind

router = APIRouter(prefix="/v1/nodes", tags=["nodes"])

_RANGE_TO_DELTA: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
_RANGE_TO_BUCKET: dict[str, str] = {
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
    cutoff_minutes = 30
    if isinstance(node.calibration, dict):
        cutoff_minutes = int(node.calibration.get("offline_after_minutes", cutoff_minutes))
    if node.last_seen_at is None:
        return False
    return (now - node.last_seen_at) <= timedelta(minutes=cutoff_minutes)


async def _find_room_node(plant: Node, session: AsyncSession) -> Node | None:
    """The room-kind node assigned to `plant`, if any.

    Two lookup conventions, tried in order (see docs/api.md): a room node
    whose own `room_id` matches the plant's, or — the convention Carl's hub
    actually uses — a room node whose `id` equals the plant's `room_id`.
    """
    if not plant.room_id:
        return None
    stmt = select(Node).where(
        Node.hub_id == plant.hub_id,
        Node.room_id == plant.room_id,
        Node.kind == NodeKind.room.value,
    )
    room_node = (await session.scalars(stmt)).first()
    if room_node is not None:
        return room_node
    stmt2 = select(Node).where(
        Node.hub_id == plant.hub_id,
        Node.id == plant.room_id,
        Node.kind == NodeKind.room.value,
    )
    return (await session.scalars(stmt2)).first()


async def _room_env_for(plant: Node, session: AsyncSession) -> RoomEnv | None:
    """Embedded `room` field for a plant node — mirrors the graft the hub
    performs on `/api/nodes` before returning it. `None` for room/camera
    nodes themselves, or a plant with no room assigned or no room reading yet.
    """
    if plant.kind != NodeKind.plant.value:
        return None
    room_node = await _find_room_node(plant, session)
    if room_node is None:
        return None
    latest = await _latest_reading(room_node.id, session)
    if latest is None:
        return None
    return RoomEnv(
        source=room_node.id,
        ts=latest.ts,
        temperature_c=latest.temperature_c,
        humidity_pct=latest.humidity_pct,
        pressure_hpa=latest.pressure_hpa,
        illuminance_lux=latest.illuminance_lux,
    )


async def _to_node_out(node: Node, session: AsyncSession, now: datetime) -> NodeOut:
    latest = await _latest_reading(node.id, session)
    room = await _room_env_for(node, session)
    return NodeOut(
        id=node.id,
        mac=node.mac,
        name=node.name,
        node_type=NodeKind(node.kind),
        room_id=node.room_id or "",  # Carl's contract: empty string, never null
        hub_id=node.hub_id,
        species=node.species,
        online=_is_online(node, now),
        last_seen=node.last_seen_at,
        battery_pct=node.battery_pct,
        latest=latest,
        calibration=node.calibration,
        room=room,
    )


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    kind: NodeKind | None = Query(
        None,
        description=(
            "Filter by node kind. Omit to get plant+room only (matches Carl's "
            "node_type enum — camera is a Norman-only bookkeeping kind that "
            "would fail to decode in the iOS app's NodeType enum, so it's "
            "excluded unless explicitly requested)."
        ),
    ),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[NodeOut]:
    """All nodes the user owns across all hubs. Optional `kind` filter."""
    stmt = select(Node).join(Hub, Hub.id == Node.hub_id).where(Hub.owner_id == user.id)
    if kind is not None:
        stmt = stmt.where(Node.kind == kind.value)
    else:
        stmt = stmt.where(Node.kind != NodeKind.camera.value)
    nodes = (await session.scalars(stmt)).all()
    now = datetime.now(timezone.utc)
    return [await _to_node_out(n, session, now) for n in nodes]


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(
    node_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> NodeOut:
    node = await _ensure_owned_node(node_id, user, session)
    return await _to_node_out(node, session, datetime.now(timezone.utc))


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

    by_ts: dict[datetime, dict[str, float]] = {}
    for r in rows:
        if r.metric not in KNOWN_METRICS:
            continue
        by_ts.setdefault(r.ts, {})[r.metric] = r.value

    samples = [_build_reading(ts, vals) for ts, vals in sorted(by_ts.items())]
    return HistoryOut(node_id=node_id, range=range, samples=samples)


@router.get("/{plant_id}/snapshot", response_model=SnapshotOut)
async def get_plant_snapshot(
    plant_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SnapshotOut:
    """Joined view: plant probe readings + the ambient from its assigned room.

    Mirrors the join the hub does on the LAN at `/api/nodes/{id}` for plant nodes.
    """
    plant = await _ensure_owned_node(plant_id, user, session)
    if plant.kind != NodeKind.plant.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Node {plant_id} is kind={plant.kind}, snapshot is plant-only",
        )

    now = datetime.now(timezone.utc)
    plant_out = await _to_node_out(plant, session, now)

    room_node = await _find_room_node(plant, session)
    room_out = await _to_node_out(room_node, session, now) if room_node is not None else None

    return SnapshotOut(plant=plant_out, room=room_out)


@router.get("/{plant_id}/predictions", response_model=list[PredictionOut])
async def get_plant_predictions(
    plant_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Prediction]:
    """ML output for one plant. Returns `[]` until the ML pipeline lands."""
    await _ensure_owned_node(plant_id, user, session)
    stmt = (
        select(Prediction)
        .where(Prediction.node_id == plant_id)
        .order_by(Prediction.ts.desc())
        .limit(limit)
    )
    return list(await session.scalars(stmt))
