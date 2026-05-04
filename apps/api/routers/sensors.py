from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Reading, Sensor, User
from apps.api.schemas import LatestReadingOut, ReadingOut
from apps.api.security import current_user

router = APIRouter(prefix="/v1/sensors", tags=["sensors"])


_INTERVAL_MAP: dict[str, str] = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "1d": "1 day",
}


async def _ensure_owned(sensor_id: str, user: User, session: AsyncSession) -> Sensor:
    sensor = await session.get(Sensor, sensor_id)
    if sensor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sensor not found")
    hub = await session.get(Hub, sensor.hub_id)
    if hub is None or hub.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sensor not found")
    return sensor


@router.get("/{sensor_id}/latest", response_model=LatestReadingOut)
async def latest(
    sensor_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> LatestReadingOut:
    await _ensure_owned(sensor_id, user, session)

    # one row per metric, the most recent ts
    sub = (
        select(Reading.metric, func.max(Reading.ts).label("ts"))
        .where(Reading.sensor_id == sensor_id)
        .group_by(Reading.metric)
        .subquery()
    )
    stmt = select(Reading).join(
        sub, and_(Reading.metric == sub.c.metric, Reading.ts == sub.c.ts)
    ).where(Reading.sensor_id == sensor_id)
    rows = (await session.scalars(stmt)).all()
    return LatestReadingOut(
        sensor_id=sensor_id,
        metrics={r.metric: ReadingOut(ts=r.ts, metric=r.metric, value=r.value) for r in rows},
    )


@router.get("/{sensor_id}/readings", response_model=list[ReadingOut])
async def readings(
    sensor_id: str,
    metric: str | None = Query(None),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    interval: str | None = Query(None, description="Downsample window; e.g. 5m, 1h"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ReadingOut]:
    await _ensure_owned(sensor_id, user, session)

    if to is None:
        to = datetime.now(timezone.utc)
    if from_ is None:
        from_ = to - timedelta(hours=24)

    if interval:
        bucket = _INTERVAL_MAP.get(interval)
        if not bucket:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Unsupported interval: {interval}"
            )
        sql = f"""
            SELECT time_bucket(:bucket, ts) AS ts, metric, avg(value) AS value
            FROM readings
            WHERE sensor_id = :sid
              AND ts >= :from_ AND ts <= :to
              {"AND metric = :metric" if metric else ""}
            GROUP BY 1, 2
            ORDER BY 1
        """
        params: dict = {"bucket": bucket, "sid": sensor_id, "from_": from_, "to": to}
        if metric:
            params["metric"] = metric
        result = await session.execute(text(sql), params)
        return [ReadingOut(ts=r.ts, metric=r.metric, value=r.value) for r in result]

    stmt = select(Reading).where(
        Reading.sensor_id == sensor_id, Reading.ts >= from_, Reading.ts <= to
    )
    if metric:
        stmt = stmt.where(Reading.metric == metric)
    stmt = stmt.order_by(Reading.ts)
    rows = (await session.scalars(stmt)).all()
    return [ReadingOut(ts=r.ts, metric=r.metric, value=r.value) for r in rows]
