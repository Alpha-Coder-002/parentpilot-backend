"""Socket.IO event handlers for device status updates and signaling."""
import logging
from datetime import datetime, timezone
import uuid
import socketio
import redis.asyncio as aioredis
from fakeredis import aioredis as fakeredis_async
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.auth_service import decode_token
from app.models.device import Device
from app.models.user import User
from app.models.pairing import Pairing
from app.db.database import AsyncSessionLocal
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", logger=True, engineio_logger=True)

# Map: socket_id → user_id
_socket_users: dict[str, str] = {}
# Map: user_id → socket_id
_user_sockets: dict[str, str] = {}

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        if settings.REDIS_URL.startswith("fake://") or (settings.DEV_MODE and settings.REDIS_URL == "redis://localhost:6379"):
            try:
                import socket as _socket
                _socket.create_connection(("localhost", 6379), timeout=1).close()
                _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except OSError:
                _redis = fakeredis_async.FakeRedis(decode_responses=True)
        else:
            _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None):
    token = (auth or {}).get("token")
    user_id = None
    if token:
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            user_id = payload["sub"]

    if not user_id:
        if settings.DEV_MODE:
            user_id = f"dev:{sid}"
        else:
            await sio.disconnect(sid)
            return

    _socket_users[sid] = user_id
    _user_sockets[user_id] = sid

    # Mark device online only for real authenticated users
    if not user_id.startswith("dev:"):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.user_id == uuid.UUID(user_id)))
            device = result.scalar_one_or_none()
            if device:
                device.is_online = True
                device.last_seen = datetime.now(timezone.utc)
                await db.commit()
                redis = await _get_redis()
                await redis.setex(f"online:{device.id}", 60, "1")

    logger.info(f"[WS] connected user={user_id} sid={sid}")


@sio.event
async def disconnect(sid: str):
    user_id = _socket_users.pop(sid, None)
    if user_id:
        _user_sockets.pop(user_id, None)
        if user_id.startswith("dev:"):
            logger.info(f"[WS] disconnected sid={sid}")
            return
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Device).where(Device.user_id == uuid.UUID(user_id)))
            device = result.scalar_one_or_none()
            if device:
                device.is_online = False
                await db.commit()
                redis = await _get_redis()
                await redis.delete(f"online:{device.id}")
    logger.info(f"[WS] disconnected sid={sid}")


async def _get_recipients(sender_sid: str, sender_user_id: str) -> list[str]:
    """Return sids that should receive events from this sender.
    DEV_MODE: broadcast to all other connected sockets.
    Production: look up paired helper via DB.
    """
    if settings.DEV_MODE:
        return [sid for sid in _socket_users if sid != sender_sid]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Pairing).where(
                Pairing.parent_id == sender_user_id,
                Pairing.status == "active",
            )
        )
        pairing = result.scalar_one_or_none()
        if not pairing:
            return []
        helper_sid = _user_sockets.get(str(pairing.helper_id))
        return [helper_sid] if helper_sid else []
    return []


# Status events: parent → backend → helper(s)

@sio.on("status:battery")
async def on_battery(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("status:battery", data, to=recipient)


@sio.on("status:network")
async def on_network(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("status:network", data, to=recipient)


@sio.on("status:screen")
async def on_screen(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("status:screen", data, to=recipient)


# SOS

@sio.on("sos:triggered")
async def on_sos(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("sos:triggered", data, to=recipient)
    logger.warning(f"[SOS] triggered by user={user_id}")


# Screenshot-based screen view (Phase 2 — no approval required)

@sio.on("screen:view:start")
async def on_screen_view_start(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("screen:view:start", data, to=recipient)


@sio.on("screen:view:stop")
async def on_screen_view_stop(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("screen:view:stop", data, to=recipient)


@sio.on("screen:frame")
async def on_screen_frame(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("screen:frame", data, to=recipient)


# Remote Control commands: helper → parent (Phase 3)

@sio.on("command:tap")
async def on_command_tap(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    logger.info(f"[TAP] from sid={sid} user={user_id} data={data} all_sockets={list(_socket_users.keys())}")
    if not user_id:
        return
    recipients = await _get_recipients(sid, user_id)
    logger.info(f"[TAP] forwarding to recipients={recipients}")
    for recipient in recipients:
        await sio.emit("command:tap", data, to=recipient)


@sio.on("command:swipe")
async def on_command_swipe(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("command:swipe", data, to=recipient)


@sio.on("command:keyevent")
async def on_command_keyevent(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("command:keyevent", data, to=recipient)


# WebRTC Signaling (Phase 2) — relay between helper and parent

@sio.on("signal:offer")
async def on_signal_offer(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("signal:offer", data, to=recipient)


@sio.on("signal:answer")
async def on_signal_answer(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("signal:answer", data, to=recipient)


@sio.on("signal:ice")
async def on_signal_ice(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("signal:ice", data, to=recipient)


@sio.on("debug:status")
async def on_debug_status(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    for recipient in await _get_recipients(sid, user_id):
        await sio.emit("debug:status", data, to=recipient)


@sio.on("sos:acknowledged")
async def on_sos_ack(sid: str, data: dict):
    user_id = _socket_users.get(sid)
    if not user_id:
        return
    # Find parent's sid via pairing
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Pairing).where(Pairing.helper_id == user_id, Pairing.status == "active")
        )
        pairing = result.scalar_one_or_none()
        if pairing and pairing.parent_id:
            parent_sid = _user_sockets.get(str(pairing.parent_id))
            if parent_sid:
                await sio.emit("sos:acknowledged", data, to=parent_sid)
