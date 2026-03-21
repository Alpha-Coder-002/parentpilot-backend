from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis
from app.db.database import get_db
from app.dependencies import get_redis
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    phone_number: str
    role: str  # 'parent' or 'helper'


class VerifyOtpRequest(BaseModel):
    phone_number: str
    otp: str
    role: str
    display_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    role: str


@router.post("/register")
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    if body.role not in ("parent", "helper"):
        raise HTTPException(status_code=400, detail="role must be 'parent' or 'helper'")
    await auth_service.send_otp(body.phone_number, redis)
    return {"message": "OTP sent"}


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(
    body: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    if body.role not in ("parent", "helper"):
        raise HTTPException(status_code=400, detail="Invalid role")

    valid = await auth_service.verify_otp(body.phone_number, body.otp, redis)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid or expired OTP")

    user = await auth_service.get_or_create_user(body.phone_number, body.role, db)
    if body.display_name:
        user.display_name = body.display_name
        await db.commit()

    access = auth_service.create_access_token(str(user.id))
    refresh = auth_service.create_refresh_token(str(user.id))
    return TokenResponse(access_token=access, refresh_token=refresh, user_id=str(user.id), role=user.role)
