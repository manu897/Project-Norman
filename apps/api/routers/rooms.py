"""Rooms — hub-scoped logical spaces a plant lives in.

Created on Norman by hub upload; user-edited names land here next time the
hub batches. iOS reads these to render the room-grouped plant list.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Node, Room, User
from apps.api.routers.nodes import _to_node_out
from apps.api.schemas import RoomDetailOut, RoomOut
from apps.api.security import current_user

router = APIRouter(prefix="/v1/rooms", tags=["rooms"])


@router.get("", response_model=list[RoomOut])
async def list_rooms(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Room]:
    """Every room across every hub the user owns."""
    stmt = select(Room).join(Hub, Hub.id == Room.hub_id).where(Hub.owner_id == user.id)
    return list(await session.scalars(stmt))


@router.get("/{room_id}", response_model=RoomDetailOut)
async def get_room(
    room_id: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RoomDetailOut:
    """A room + all nodes assigned to it (plants + the room-kind node itself)."""
    # Room ids are hub-scoped; we need to disambiguate by ownership.
    stmt = (
        select(Room)
        .join(Hub, Hub.id == Room.hub_id)
        .where(Room.id == room_id, Hub.owner_id == user.id)
    )
    room = (await session.scalars(stmt)).first()
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found")

    nodes_stmt = select(Node).where(
        Node.hub_id == room.hub_id,
        # A node "belongs" to the room if it's assigned to it (plants) OR
        # if it IS the room-kind node identified by this room id.
        ((Node.room_id == room.id) | (Node.id == room.id)),
    )
    nodes = (await session.scalars(nodes_stmt)).all()
    now = datetime.now(timezone.utc)
    node_outs = [await _to_node_out(n, session, now) for n in nodes]

    return RoomDetailOut(
        id=room.id,
        hub_id=room.hub_id,
        name=room.name,
        created_at=room.created_at,
        nodes=node_outs,
    )
