import asyncio
import os
import sys
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from govnotify.storage.postgres import DocumentORM, get_engine, get_session_factory

async def find_duplicates():
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    async with session_factory() as session:
        # Find duplicate content_hashes
        stmt = (
            select(DocumentORM.content_hash, func.count(DocumentORM.id))
            .group_by(DocumentORM.content_hash)
            .having(func.count(DocumentORM.id) > 1)
        )
        result = await session.execute(stmt)
        duplicates = result.all()
        
        print(f"Found {len(duplicates)} duplicate content hashes.")
        for content_hash, count in duplicates:
            if not content_hash: continue
            print(f"Hash: {content_hash}, Count: {count}")
            
            # Get details for these duplicates
            details_stmt = select(DocumentORM.id, DocumentORM.title, DocumentORM.source_id, DocumentORM.ingested_at).where(DocumentORM.content_hash == content_hash)
            details_result = await session.execute(details_stmt)
            for row in details_result.all():
                print(f"  - ID: {row.id}, Source: {row.source_id}, Title: {row.title[:50]}, Ingested: {row.ingested_at}")

        # Find duplicate titles within same source
        stmt = (
            select(DocumentORM.title, DocumentORM.source_id, func.count(DocumentORM.id))
            .group_by(DocumentORM.title, DocumentORM.source_id)
            .having(func.count(DocumentORM.id) > 1)
        )
        result = await session.execute(stmt)
        title_duplicates = result.all()
        
        print(f"\nFound {len(title_duplicates)} duplicate titles within same source.")
        for title, source_id, count in title_duplicates:
            print(f"Title: {title[:50]}, Source: {source_id}, Count: {count}")
            
            # Get details
            details_stmt = select(DocumentORM.id, DocumentORM.content_hash, DocumentORM.ingested_at).where(DocumentORM.title == title, DocumentORM.source_id == source_id)
            details_result = await session.execute(details_stmt)
            for row in details_result.all():
                print(f"  - ID: {row.id}, Hash: {row.content_hash}, Ingested: {row.ingested_at}")

if __name__ == "__main__":
    asyncio.run(find_duplicates())
