import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from fakeredis import aioredis as fakeredis_async
from app.db.database import get_db
from app.services.auth_service import decode_token
from app.models.user import User
from app.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer()

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        if settings.REDIS_URL.startswith("fake://") or settings.DEV_MODE and settings.REDIS_URL == "redis://localhost:6379":
            try:
                import socket
                socket.create_connection(("localhost", 6379), timeout=1).close()
                _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except OSError:
                # Redis not running — use fakeredis
                _redis_pool = fakeredis_async.FakeRedis(decode_responses=True)
        else:
            _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
