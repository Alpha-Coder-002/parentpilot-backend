import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.dependencies import get_current_user
from app.services import pairing_service
from app.models.user import User

router = APIRouter(prefix="/api/pairing", tags=["pairing"])


class AcceptRequest(BaseModel):
    code: str


@router.post("/generate-code")
async def generate_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "helper":
        raise HTTPException(status_code=403, detail="Only helpers can generate pairing codes")
    pairing = await pairing_service.generate_pairing_code(current_user.id, db)
    return {"pairing_id": str(pairing.id), "code": pairing.pairing_code, "expires_at": pairing.code_expires_at}


@router.post("/accept")
async def accept_pairing(
    body: AcceptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "parent":
        raise HTTPException(status_code=403, detail="Only parents can accept pairing codes")
    pairing = await pairing_service.accept_pairing(body.code, current_user.id, db)
    if not pairing:
        raise HTTPException(status_code=404, detail="Invalid or expired pairing code")
    return {"pairing_id": str(pairing.id), "status": pairing.status}


@router.get("/status")
async def get_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pairing = await pairing_service.get_active_pairing(current_user.id, current_user.role, db)
    if not pairing:
        return {"status": "unpaired"}
    return {
        "status": pairing.status,
        "pairing_id": str(pairing.id),
        "helper_id": str(pairing.helper_id),
        "parent_id": str(pairing.parent_id) if pairing.parent_id else None,
    }


@router.delete("/{pairing_id}")
async def revoke_pairing(
    pairing_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models.pairing import Pairing
    result = await db.execute(select(Pairing).where(Pairing.id == pairing_id))
    pairing = result.scalar_one_or_none()
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing not found")
    if str(pairing.helper_id) != str(current_user.id) and str(pairing.parent_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your pairing")
    pairing.status = "revoked"
    await db.commit()
    return {"status": "revoked"}
