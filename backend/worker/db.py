"""Worker-side DB access.

Celery tasks run under asyncio.run() per invocation, so each task builds
a fresh engine/session and disposes it — no engine can be shared across
event loops."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings


@asynccontextmanager
async def task_session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
