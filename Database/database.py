from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession
)
from Database.models import Base

engine = create_async_engine("sqlite+aiosqlite:///reports.db", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] Таблицы созданы или уже существуют.")


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session