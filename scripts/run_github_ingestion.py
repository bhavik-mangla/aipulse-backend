import asyncio
import gc
import sys
import os
from datetime import datetime, timezone
import structlog
from croniter import croniter
from sqlalchemy import select

# Ensure src is in the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from govnotify.config import get_settings
from govnotify.logging_config import setup_logging
from govnotify.processing.pipeline import ProcessingPipeline
from govnotify.sources.registry import SourceRegistry
from govnotify.storage.postgres import (
    DocumentORM,
    IngestLogORM,
    SourceORM,
    get_engine,
    get_session_factory,
)
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)

async def run_ingestion():
    setup_logging()
    settings = get_settings()
    
    # Validate Database URL
    db_url = settings.database_url
    if not db_url or "change-me" in db_url:
        logger.error("invalid_database_url", url_provided=db_url)
        print("\nERROR: DATABASE_URL is missing or using default value.")
        print("Please ensure you have added the 'DATABASE_URL' secret to your GitHub repository.")
        sys.exit(1)
        
    try:
        engine = get_engine()
    except Exception as e:
        logger.error("database_engine_creation_failed", error=str(e))
        print(f"\nERROR: Failed to create database engine: {e}")
        sys.exit(1)
        
    session_factory = get_session_factory(engine)
    
    now = get_utc_now()
    results = {"triggered": [], "skipped": [], "errors": []}

    # One pipeline, shared by every source. Building it per source gave each
    # one an empty deduplication index that was discarded afterwards, so the
    # same story carried by several outlets was stored several times.
    pipeline = ProcessingPipeline(enable_llm=settings.enable_llm)

    async with session_factory() as session:
        # Seed the dedup indices with recently ingested documents so
        # near-duplicate detection spans runs, not just this one.
        await pipeline.dedup.load_recent_window(session)

        stmt = select(SourceORM).where(SourceORM.enabled == True)
        result = await session.execute(stmt)
        sources_orm = result.scalars().all()
        
        logger.info("github_actions_ingest_start", source_count=len(sources_orm))
        
        for s_orm in sources_orm:
            source_id = s_orm.id
            schedule_cron = s_orm.schedule_cron or "0 4 * * *"
            last_fetched_at = s_orm.last_fetched_at

            # Check if due
            is_due = True
            if last_fetched_at:
                try:
                    if last_fetched_at.tzinfo is None:
                        last_fetched_at = last_fetched_at.replace(tzinfo=timezone.utc)
                    iter = croniter(schedule_cron, last_fetched_at)
                    next_run = iter.get_next(datetime)
                    is_due = next_run <= now
                except Exception as e:
                    logger.error("cron_check_failed", source_id=source_id, error=str(e))
                    is_due = True

            if not is_due:
                results["skipped"].append(source_id)
                continue
            
            logger.info("ingesting_source", source_id=source_id)
            results["triggered"].append(source_id)
            
            # Start Ingestion for this source
            ingest_start_time = get_utc_now()
            ingest_log = IngestLogORM(
                source_id=source_id,
                started_at=ingest_start_time,
                status="running",
            )
            session.add(ingest_log)
            await session.flush()
            
            try:
                source = SourceRegistry.get(source_id)

                fetched_count = 0
                new_count = 0
                dup_count = 0
                error_details = []
                
                # Deduplication callback (Identical to Celery logic)
                source.is_duplicate_callback = lambda doc: pipeline.check_duplicate(doc, session=session)
                
                async for raw_doc in source.fetch(since=last_fetched_at):
                    fetched_count += 1
                    logger.info("ingest_doc_fetched", source_id=source_id, title=raw_doc.title[:50])
                    
                    try:
                        result = await pipeline.process(raw_doc, session=session)
                        
                        if result.error:
                            error_details.append(result.error)
                            continue
                        
                        if result.is_duplicate:
                            dup_count += 1
                            continue
                        
                        if result.skipped:
                            continue

                        if result.document:
                            doc = result.document
                            doc_orm = DocumentORM(
                                id=doc.id,
                                source_id=source_id,
                                source_url=str(doc.source_url),
                                fetch_url=str(doc.fetch_url) if doc.fetch_url else None,
                                title=doc.title,
                                clean_text=doc.clean_text,
                                summary=doc.summary,
                                categories=[c.value for c in doc.categories],
                                primary_category=doc.primary_category.value if doc.primary_category else None,
                                regions=doc.regions,
                                departments=doc.departments,
                                impact_tier=getattr(doc, "impact_tier", "Medium"),
                                country=getattr(doc, "country", None),
                                image_url=getattr(doc, "image_url", None),
                                image_search_query=getattr(doc, "image_search_query", None),
                                ingested_at=get_utc_now(),
                                published_at=doc.published_at,
                                entities=getattr(doc, "entities", {}),
                                language=doc.language,
                                content_hash=doc.content_hash,
                                simhash=doc.simhash,
                                is_duplicate=False,
                                confidence_score=doc.confidence_score,
                            )
                            session.add(doc_orm)
                            new_count += 1
                            
                            if new_count % 5 == 0:
                                await session.commit()
                                gc.collect()

                    except Exception as doc_exc:
                        logger.error("ingest_doc_processing_failed", source_id=source_id, error=str(doc_exc))
                        error_details.append(str(doc_exc))
                
                # Update source last fetched
                s_orm.last_fetched_at = ingest_start_time
                
                ingest_log.items_fetched = fetched_count
                ingest_log.items_new = new_count
                ingest_log.items_duplicate = dup_count
                ingest_log.errors = len(error_details)
                ingest_log.error_details = error_details[:20]
                ingest_log.status = "completed"
                ingest_log.completed_at = get_utc_now()
                
                await session.commit()
                gc.collect()
                
            except Exception as e:
                logger.error("ingest_source_failed", source_id=source_id, error=str(e))
                ingest_log.status = "failed"
                ingest_log.completed_at = get_utc_now()
                ingest_log.error_message = str(e)
                ingest_log.error_details = [str(e)]
                await session.commit()
                results["errors"].append({"source_id": source_id, "error": str(e)})

    await engine.dispose()
    logger.info("github_actions_ingest_complete", results=results)

if __name__ == "__main__":
    asyncio.run(run_ingestion())
