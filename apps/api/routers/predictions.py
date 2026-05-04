from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Prediction, User
from apps.api.schemas import PredictionOut
from apps.api.security import current_user

router = APIRouter(prefix="/v1/predictions", tags=["predictions"])


@router.get("/{hub_id}", response_model=list[PredictionOut])
async def latest_for_hub(
    hub_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Prediction]:
    hub = await session.get(Hub, hub_id)
    if hub is None or hub.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hub not found")
    stmt = (
        select(Prediction)
        .where(Prediction.hub_id == hub_id)
        .order_by(Prediction.ts.desc())
        .limit(20)
    )
    return list(await session.scalars(stmt))
