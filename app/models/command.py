from datetime import datetime
from sqlalchemy import String, DateTime, BigInteger, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
import uuid
from app.db.database import Base


class CommandLog(Base):
    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pairing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pairings.id"), nullable=False)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent, executed, failed


class DeviceStatus(Base):
    __tablename__ = "device_status"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    battery_level: Mapped[int | None]
    is_charging: Mapped[bool | None]
    network_type: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
