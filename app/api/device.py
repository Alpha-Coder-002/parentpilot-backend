import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from app.db.database import get_db
from app.dependencies import get_current_user, get_redis
from app.models.device import Device
from app.models.user import User

router = APIRouter(prefix="/api/device", tags=["device"])


class RegisterDeviceRequest(BaseModel):
    device_name: str
    platform: str  # 'android' or 'ios'
    fcm_token: str | None = None


@router.post("/register")
async def register_device(
    body: RegisterDeviceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Device).where(Device.user_id == current_user.id))
    device = result.scalar_one_or_none()
    if device:
        device.device_name = body.device_name
        device.platform = body.platform
        device.fcm_token = body.fcm_token
    else:
        device = Device(
            user_id=current_user.id,
            device_name=body.device_name,
            platform=body.platform,
            fcm_token=body.fcm_token,
        )
        db.add(device)
    await db.commit()
    await db.refresh(device)
    return {"device_id": str(device.id)}


@router.put("/heartbeat")
async def heartbeat(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    result = await db.execute(select(Device).where(Device.user_id == current_user.id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not registered")
    device.is_online = True
    device.last_seen = datetime.now(timezone.utc)
    await db.commit()
    await redis.setex(f"online:{device.id}", 60, "1")
    return {"status": "ok"}


@router.get("/status/{parent_device_id}")
async def get_device_status(
    parent_device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    result = await db.execute(select(Device).where(Device.id == parent_device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    is_online = await redis.exists(f"online:{device.id}") > 0
    return {
        "device_id": str(device.id),
        "device_name": device.device_name,
        "is_online": is_online,
        "last_seen": device.last_seen,
        "fcm_token": bool(device.fcm_token),
    }
