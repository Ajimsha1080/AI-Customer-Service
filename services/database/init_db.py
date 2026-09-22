import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from services.database.session import Base
from services.database.models import *
from apps.api.config import settings

async def init_db():
    print(f"Initializing enterprise database schema with URL: {settings.DATABASE_URL}")
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            if "postgresql" in settings.DATABASE_URL:
                try:
                    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    print("✓ PostgreSQL pgvector extension verified.")
                except Exception as ve:
                    print(f"pgvector extension warning: {ve}")
            await conn.run_sync(Base.metadata.create_all)
        print("✓ Enterprise database tables & indexes initialized successfully.")
    except Exception as e:
        print(f"PostgreSQL connection failed ({e}). Falling back to SQLite for local development...")
        sqlite_url = "sqlite+aiosqlite:///./dev_hospitality.db"
        sqlite_engine = create_async_engine(sqlite_url)
        async with sqlite_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print(f"✓ SQLite database initialized at {sqlite_url}")

if __name__ == "__main__":
    asyncio.run(init_db())
