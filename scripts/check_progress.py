
import asyncio
import os
import sys
from datetime import datetime, timezone

# Ensure src is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from govnotify.storage.postgres import get_engine, get_session_factory, DocumentORM
from sqlalchemy import select, func

async def check_progress():
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    async with session_factory() as session:
        # Total count
        res = await session.execute(select(func.count(DocumentORM.id)))
        total = res.scalar()
        
        # Ingested in last 24 hours
        from datetime import timedelta
        start_time = datetime.now(timezone.utc) - timedelta(hours=24)
        res = await session.execute(
            select(func.count(DocumentORM.id)).where(DocumentORM.ingested_at >= start_time)
        )
        recent = res.scalar()
        
        # Sample of latest docs
        res = await session.execute(
            select(DocumentORM.title, DocumentORM.source_id, DocumentORM.ingested_at)
            .order_by(DocumentORM.ingested_at.desc())
            .limit(5)
        )
        latest = res.all()
        
        print(f"Total documents: {total}")
        print(f"Documents ingested after restart: {recent}")
        print("\nLatest 5 documents:")
        for title, sid, ingested in latest:
            print(f"- [{sid}] {title} (Ingested: {ingested})")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_progress())
