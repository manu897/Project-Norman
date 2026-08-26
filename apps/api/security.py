import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import get_settings
from apps.api.db import get_session
from apps.api.models import Hub, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
settings = get_settings()


# --- User passwords (bcrypt) ---


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# --- User JWT (read APIs) ---


def create_access_token(user_id: UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


async def current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise creds_error
    except JWTError as exc:
        raise creds_error from exc

    user = await session.get(User, UUID(user_id))
    if user is None:
        raise creds_error
    return user


async def current_superuser(user: User = Depends(current_user)) -> User:
    """Gate for /v1/admin/*. A valid JWT alone isn't enough — the account
    behind it must have `is_superuser` set, which is never settable through
    the API (see the migration note in models.py)."""
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


# --- Per-hub API token (ingest) ---

HUB_TOKEN_PREFIX = "ch_"  # carl-hub
HUB_TOKEN_BYTES = 32


def generate_hub_token() -> str:
    """Plain-text bearer token shown to the user once at hub-create time."""
    return HUB_TOKEN_PREFIX + secrets.token_urlsafe(HUB_TOKEN_BYTES)


def hash_hub_token(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_hub_token(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def hub_from_token(
    hub_id: str,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Hub:
    """FastAPI dependency: resolve `{hub_id}` + `Authorization: Bearer …` to a Hub."""
    auth_err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid hub credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise auth_err
    token = authorization.split(" ", 1)[1].strip()

    hub = await session.get(Hub, hub_id)
    if hub is None or hub.api_token_hash is None:
        raise auth_err
    if not verify_hub_token(token, hub.api_token_hash):
        raise auth_err
    return hub
