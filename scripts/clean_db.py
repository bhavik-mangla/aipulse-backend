
import asyncio
import os
import sys

# Ensure src is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from govnotify.storage.postgres import get_engine, Base
from govnotify.storage.qdrant import get_qdrant_client, delete_collection, create_collection
from govnotify.storage.redis_store import get_redis_client
from sqlalchemy import text

async def clean_postgres():
    print("Cleaning PostgreSQL...")
    engine = get_engine()
    
    # Sync helper for dropping/creating
    def drop_and_create(connection):
        Base.metadata.drop_all(connection)
        Base.metadata.create_all(connection)

    async with engine.begin() as conn:
        await conn.run_sync(drop_and_create)
    
    print("PostgreSQL cleaned and schema recreated.")
    await engine.dispose()

async def clean_qdrant():
    print("Cleaning Qdrant...")
    client = get_qdrant_client()
    delete_collection(client)
    create_collection(client)
    print("Qdrant cleaned.")

async def clean_redis():
    print("Cleaning Redis...")
    client = get_redis_client()
    await client.flushdb()
    print("Redis cleaned.")
    await client.aclose()

async def main():
    await clean_postgres()
    await clean_qdrant()
    await clean_redis()
    print("All databases cleaned successfully.")

if __name__ == "__main__":
    asyncio.run(main())
