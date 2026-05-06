import asyncio
import os
import sys
from datetime import timedelta

# Ensure src is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from govnotify.utils.time import get_utc_now
from govnotify.storage.postgres import get_engine, get_session_factory, SourceORM
from govnotify.models.source import SourceType
from govnotify.sources.registry import SourceRegistry
from sqlalchemy import select, update

# Import all sources to register them
import govnotify.sources # noqa

async def seed_new_sources():
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    # Get all sources from registry
    sources = SourceRegistry.all()
    print(f"Found {len(sources)} sources in registry.")
    
    since = get_utc_now() - timedelta(days=30)
    
    async with session_factory() as session:
        for source in sources:
            source_id = source.source_id
            config = source.source_config
            print(f"Syncing source: {source_id}")
            
            # Check if exists
            res = await session.execute(select(SourceORM).where(SourceORM.id == source_id))
            existing = res.scalar_one_or_none()
            
            if existing:
                existing.name = config.name
                existing.url = str(config.url)
                existing.category_tags = config.category_tags
                existing.region_tags = config.region_tags
                # ONLY set last_fetched_at if it's currently None
                if existing.last_fetched_at is None:
                    existing.last_fetched_at = since
                # Update other fields from config
                existing.schedule_cron = config.schedule_cron
                existing.crawler_class = config.crawler_class
                existing.source_type = config.source_type.value
            else:
                new_src = SourceORM(
                    id=source_id,
                    name=config.name,
                    source_type=config.source_type.value,
                    url=str(config.url),
                    region_tags=config.region_tags,
                    category_tags=config.category_tags,
                    language=config.language,
                    crawler_class=config.crawler_class,
                    schedule_cron=config.schedule_cron,
                    last_fetched_at=since,
                    enabled=True
                )
                session.add(new_src)
        
        await session.commit()
    
    print("Seeding and reset complete.")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_new_sources())
