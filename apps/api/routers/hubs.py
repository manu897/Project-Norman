from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, User
from apps.api.schemas import HubCreate, HubCreateOut, HubOut
from apps.api.security import current_user, generate_hub_token, hash_hub_token

router = APIRouter(prefix="/v1/hubs", tags=["hubs"])


@router.get("", response_model=list[HubOut])
async def list_hubs(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[Hub]:
    result = await session.scalars(select(Hub).where(Hub.owner_id == user.id))
    return list(result)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=HubCreateOut)
async def create_hub(
    body: HubCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HubCreateOut:
    """Claim a hub. Returns a one-time-visible API token for hub→Norman uploads."""
    plain_token = generate_hub_token()
    hub = Hub(
        id=body.id,
        owner_id=user.id,
        name=body.name,
        location=body.location,
        api_token_hash=hash_hub_token(plain_token),
    )
    session.add(hub)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Hub id already exists") from None
    await session.refresh(hub)
    return HubCreateOut(
        id=hub.id,
        name=hub.name,
        location=hub.location,
        last_seen_at=hub.last_seen_at,
        created_at=hub.created_at,
        api_token=plain_token,
    )


@router.get("/{hub_id}", response_model=HubOut)
async def get_hub(
    hub_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Hub:
    hub = await session.get(Hub, hub_id)
    if hub is None or hub.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hub not found")
    return hub
