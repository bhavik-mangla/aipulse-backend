
import asyncio
import os
import sys
from datetime import timedelta
from sqlalchemy import select
from govnotify.utils.time import get_utc_now
from govnotify.storage.postgres import get_engine, get_session_factory, DocumentORM, SourceORM

async def verify_source(source_id: str):
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    print(f"\n=== Verification for {source_id} ===")
    
    async with session_factory() as session:
        # 1. Check Source last_fetched_at
        res = await session.execute(select(SourceORM).where(SourceORM.id == source_id))
        source = res.scalar_one_or_none()
        if not source:
            print(f"Error: Source {source_id} not found in DB.")
            return
        
        print(f"Source: {source.name}")
        print(f"Last Fetched At: {source.last_fetched_at}")
        
        # 2. Check latest documents
        res = await session.execute(
            select(DocumentORM)
            .where(DocumentORM.source_id == source_id)
            .order_by(DocumentORM.ingested_at.desc())
            .limit(5)
        )
        docs = res.scalars().all()
        
        if not docs:
            print("No documents found for this source.")
            return
            
        print(f"Total documents found in DB: (checking first 5)")
        for doc in docs:
            print(f"  - Title: {doc.title[:60]}...")
            print(f"    Ingested At:      {doc.ingested_at}")
            print(f"    PDF Link:         {doc.fetch_url}")
            # Verification: ingested_at should be recent
            if not doc.ingested_at:
                print("    ERROR: ingested_at is NULL!")
            if doc.ingested_at > get_utc_now() + timedelta(minutes=5):
                print("    WARNING: ingested_at is in the future!")

    await engine.dispose()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_final_sources.py <source_id>")
        sys.exit(1)
    asyncio.run(verify_source(sys.argv[1]))
