from contextlib import asynccontextmanager
import os
import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import init_db
from app.api import auth, pairing, device
from app.ws.status import sio


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="ParentPilot API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST routers
app.include_router(auth.router)
app.include_router(pairing.router)
app.include_router(device.router)

# Serve static files and web dashboard
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/dashboard")
async def dashboard():
    return FileResponse(os.path.join(_static_dir, "dashboard.html"))


# Mount Socket.IO as ASGI sub-app
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/log")
async def log_from_app(request: Request):
    body = await request.json()
    print(f"APP_LOG from {request.client.host}: {body}", flush=True)
    return {"ok": True}
