import random
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.config import get_settings

settings = get_settings()


def _hash_phone(phone: str) -> str:
    """Store hashed phone number for privacy."""
    return hashlib.sha256(phone.encode()).hexdigest()


def _otp_key(phone_hash: str) -> str:
    return f"otp:{phone_hash}"


async def send_otp(phone: str, redis: aioredis.Redis) -> str:
    """Generate OTP and store in Redis (TTL 5 min). In DEV_MODE return fixed OTP."""
    otp = settings.DEV_OTP if settings.DEV_MODE else str(random.randint(100000, 999999))
    phone_hash = _hash_phone(phone)
    await redis.setex(_otp_key(phone_hash), 300, otp)

    if not settings.DEV_MODE:
        # TODO: send via Twilio
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=f"Your ParentPilot OTP is {otp}",
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone,
        )
    return otp


async def verify_otp(phone: str, otp: str, redis: aioredis.Redis) -> bool:
    phone_hash = _hash_phone(phone)
    stored = await redis.get(_otp_key(phone_hash))
    if stored and (stored if isinstance(stored, str) else stored.decode()) == otp:
        await redis.delete(_otp_key(phone_hash))
        return True
    return False


async def get_or_create_user(phone: str, role: str, db: AsyncSession) -> User:
    phone_hash = _hash_phone(phone)
    result = await db.execute(select(User).where(User.phone_number == phone_hash))
    user = result.scalar_one_or_none()
    if not user:
        user = User(phone_number=phone_hash, role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


def create_access_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_ACCESS_EXPIRE_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "access"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "refresh"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
