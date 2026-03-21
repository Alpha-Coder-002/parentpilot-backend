from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

# Support both PostgreSQL (prod) and SQLite (local dev without Docker)
_url = settings.DATABASE_URL
if _url.startswith("postgresql"):
    DATABASE_URL = _url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(DATABASE_URL, echo=False)
else:
    DATABASE_URL = _url  # sqlite+aiosqlite:///./parentpilot.db
    engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
