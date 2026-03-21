import random
import string
from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.pairing import Pairing
from app.models.user import User


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=6))


async def generate_pairing_code(helper_id: uuid.UUID, db: AsyncSession) -> Pairing:
    """Helper creates a new pairing entry with a fresh 6-digit code."""
    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Check if there's an existing pending pairing for this helper without a parent yet
    result = await db.execute(
        select(Pairing).where(Pairing.helper_id == helper_id, Pairing.status == "pending", Pairing.parent_id == None)
    )
    pairing = result.scalar_one_or_none()
    if pairing:
        pairing.pairing_code = code
        pairing.code_expires_at = expires_at
    else:
        pairing = Pairing(
            helper_id=helper_id,
            pairing_code=code,
            code_expires_at=expires_at,
            status="pending",
        )
        db.add(pairing)

    await db.commit()
    await db.refresh(pairing)
    return pairing


async def accept_pairing(code: str, parent_id: uuid.UUID, db: AsyncSession) -> Pairing | None:
    """Parent enters 6-digit code to complete pairing."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Pairing).where(
            Pairing.pairing_code == code,
            Pairing.status == "pending",
            Pairing.code_expires_at > now,
        )
    )
    pairing = result.scalar_one_or_none()
    if not pairing:
        return None

    pairing.parent_id = parent_id
    pairing.status = "active"
    pairing.pairing_code = None  # invalidate code after use
    await db.commit()
    await db.refresh(pairing)
    return pairing


async def get_active_pairing(user_id: uuid.UUID, role: str, db: AsyncSession) -> Pairing | None:
    if role == "helper":
        result = await db.execute(
            select(Pairing).where(Pairing.helper_id == user_id, Pairing.status == "active")
        )
    else:
        result = await db.execute(
            select(Pairing).where(Pairing.parent_id == user_id, Pairing.status == "active")
        )
    return result.scalar_one_or_none()
