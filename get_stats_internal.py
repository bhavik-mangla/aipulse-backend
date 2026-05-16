
import asyncio
import os
import sys
from sqlalchemy import select, func

# Ensure /app/src is in PYTHONPATH (usually set in docker env)
sys.path.append("/app/src")

from govnotify.storage.postgres import get_engine, get_session_factory, UserORM, DocumentORM, SourceORM
from govnotify.storage.redis_store import RedisStore

async def get_stats():
    # Engine uses DATABASE_URL from environment
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    async with session_factory() as session:
        # Total Users
        result = await session.execute(select(UserORM))
        users = result.scalars().all()
        total_users = len(users)
        active_users = sum(1 for u in users if u.is_active)
        user_emails = [u.email for u in users]
        
        # Sources
        total_sources = (await session.execute(select(func.count(SourceORM.id)))).scalar() or 0
        enabled_sources = (await session.execute(
            select(func.count(SourceORM.id)).where(SourceORM.enabled == True)
        )).scalar() or 0
        
        # Documents
        total_docs = (await session.execute(select(func.count(DocumentORM.id)))).scalar() or 0
        
    # Redis Stats
    redis_store = RedisStore()
    total_visits = await redis_store.get_visitor_count()
    await redis_store.close()
    
    print("--- SYSTEM STATISTICS ---")
    print(f"Total Subscribed Users: {total_users}")
    print(f"Active Users:           {active_users}")
    print(f"Total App Views (Visits): {total_visits}")
    print(f"Total Sources:         {total_sources} ({enabled_sources} enabled)")
    print(f"Total Documents:       {total_docs}")
    print("-------------------------")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(get_stats())
