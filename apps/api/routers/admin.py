"""Superuser-only oversight endpoints — see everything, regardless of owner.

Every other router in this app scopes queries to `current_user`'s own hubs
(`Hub.owner_id == user.id`). This router deliberately does not: it exists so
one operator account can see the whole deployment (all users' hubs, nodes,
and readings) without that scoping ever leaking into the endpoints normal
accounts — including the iOS app — actually use.

Gated by `current_superuser`, which requires `User.is_superuser` — a column
with no API-facing way to set it. See models.py and migration 0004 for how
an account gets promoted (a manual `UPDATE users SET is_superuser = true`).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db import get_session
from apps.api.models import Hub, Node, Reading, User
from apps.api.routers.nodes import _to_node_out
from apps.api.schemas import AdminHubOut, AdminNodeOut, AdminStatsOut, AdminUserOut
from apps.api.security import current_superuser
from packages.schemas.telemetry import NodeKind

router = APIRouter(
    prefix="/v1/admin", tags=["admin"], dependencies=[Depends(current_superuser)]
)


@router.get("/stats", response_model=AdminStatsOut)
async def stats(session: AsyncSession = Depends(get_session)) -> AdminStatsOut:
    """Whole-deployment totals — the quickest way to answer "how much data
    is actually stored" without listing every row."""
    user_count = await session.scalar(select(func.count()).select_from(User))
    hub_count = await session.scalar(select(func.count()).select_from(Hub))
    node_count = await session.scalar(select(func.count()).select_from(Node))
    reading_count = await session.scalar(select(func.count()).select_from(Reading))
    return AdminStatsOut(
        user_count=user_count or 0,
        hub_count=hub_count or 0,
        node_count=node_count or 0,
        reading_count=reading_count or 0,
    )


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(session: AsyncSession = Depends(get_session)) -> list[AdminUserOut]:
    """Every account on this deployment, with how many hubs each owns."""
    users = (await session.scalars(select(User))).all()
    out: list[AdminUserOut] = []
    for user in users:
        hub_count = await session.scalar(
            select(func.count()).select_from(Hub).where(Hub.owner_id == user.id)
        )
        out.append(
            AdminUserOut(
                id=user.id,
                email=user.email,
                is_superuser=user.is_superuser,
                created_at=user.created_at,
                hub_count=hub_count or 0,
            )
        )
    return out


@router.get("/hubs", response_model=list[AdminHubOut])
async def list_hubs(session: AsyncSession = Depends(get_session)) -> list[AdminHubOut]:
    """Every hub on this deployment, regardless of who owns it."""
    stmt = select(Hub, User.email).join(User, User.id == Hub.owner_id)
    rows = (await session.execute(stmt)).all()
    out: list[AdminHubOut] = []
    for hub, owner_email in rows:
        node_count = await session.scalar(
            select(func.count()).select_from(Node).where(Node.hub_id == hub.id)
        )
        out.append(
            AdminHubOut(
                id=hub.id,
                name=hub.name,
                location=hub.location,
                owner_email=owner_email,
                last_seen_at=hub.last_seen_at,
                created_at=hub.created_at,
                node_count=node_count or 0,
            )
        )
    return out


@router.get("/nodes", response_model=list[AdminNodeOut])
async def list_nodes(
    kind: NodeKind | None = Query(None, description="Filter by node kind"),
    session: AsyncSession = Depends(get_session),
) -> list[AdminNodeOut]:
    """Every node on this deployment. Unlike GET /v1/nodes, camera nodes are
    included by default — this view isn't constrained by what the iOS app's
    NodeType enum can decode, since nothing here is iOS-facing."""
    stmt = select(Node, User.email).join(Hub, Hub.id == Node.hub_id).join(User, User.id == Hub.owner_id)
    if kind is not None:
        stmt = stmt.where(Node.kind == kind.value)
    rows = (await session.execute(stmt)).all()

    now = datetime.now(timezone.utc)
    out: list[AdminNodeOut] = []
    for node, owner_email in rows:
        base = await _to_node_out(node, session, now)
        out.append(AdminNodeOut(**base.model_dump(), owner_email=owner_email))
    return out
