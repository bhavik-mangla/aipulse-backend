"""
Ingestion tasks - source polling and document fetching.
Scheduled by Celery Beat every 30 minutes. Checks which sources are due for polling based on their cron schedule, then fetches new documents.
Redis distributed locks prevent duplicate runs (§9 lock:source:{source_id}).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from govnotify.tasks.celery_app import app
from govnotify.utils.time import get_utc_now

logger = structlog.get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from synchronous Celery task context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@app.task(
    name="govnotify.tasks.ingest_tasks.ingest_all_sources",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def ingest_all_sources(self):
    """
    Poll all active sources that are due for ingestion.
    Runs every 30 minutes via Celery Beat. For each enabled source,
    checks its cron schedule against last_fetched_at to decide
    whether to trigger ingestion.
    """
    return _run_async(_ingest_all_sources_async(self))


async def _ingest_all_sources_async(task):
    """Async implementation of ingest_all_sources."""
    import redis.asyncio as autoredis
    from sqlalchemy import select
    from croniter import croniter
    from govnotify.config import get_settings
    from govnotify.sources.registry import SourceRegistry
    from govnotify.storage.postgres import get_engine, get_session_factory, SourceORM

    settings = get_settings()
    engine = get_engine()
    session_factory = get_session_factory(engine)
    redis_client = autoredis.from_url(settings.redis_url)

    results = {
        "triggered": [],
        "skipped": [],
        "locked": [],
        "errors": [],
    }

    now = get_utc_now()
    
    async with session_factory() as session:
        # Fetch all enabled sources from DB to check their schedules
        stmt = select(SourceORM).where(SourceORM.enabled == True)
        result = await session.execute(stmt)
        sources_orm = result.scalars().all()
        
        logger.info("ingest_all_sources_start", source_count=len(sources_orm))
        
        for s_orm in sources_orm:
            source_id = s_orm.id
            schedule_cron = s_orm.schedule_cron or "0 4 * * *"
            last_fetched_at = s_orm.last_fetched_at

            # Check if due
            is_due = True
            if last_fetched_at:
                try:
                    # Ensure last_fetched_at is timezone-aware for croniter
                    if last_fetched_at.tzinfo is None:
                        last_fetched_at = last_fetched_at.replace(tzinfo=timezone.utc)
                    
                    iter = croniter(schedule_cron, last_fetched_at)
                    next_run = iter.get_next(datetime)
                    is_due = next_run <= now
                except Exception as e:
                    logger.error("cron_check_failed", source_id=source_id, error=str(e))
                    is_due = True # Default to True on error to be safe

            if not is_due:
                results["skipped"].append(source_id)
                continue

            # CRITICAL: Check if already running via Redis lock before triggering
            # This prevents queuing redundant tasks if one is already running
            lock_key = f"lock:source:{source_id}"
            if await redis_client.get(f"lock:{lock_key}"): # redis-py-lock uses 'lock:' prefix sometimes or we can just check the key
                # Note: actual lock key in redis might depend on how redis-py-lock stores it.
                # In _ingest_single_source_async we use lock_key = f"lock:source:{source_id}"
                # but redis_client.lock() adds its own prefix usually? No, it uses the key directly.
                pass

            # Safer check: try to acquire a short-lived "trigger" lock
            # or just check the main lock. 
            # Let's check the main lock key directly.
            is_locked = await redis_client.exists(lock_key)
            if is_locked:
                logger.info("ingest_trigger_skipped_locked", source_id=source_id)
                results["locked"].append(source_id)
                continue

            try:
                # Fan out to individual source tasks
                ingest_single_source.delay(source_id)
                results["triggered"].append(source_id)
            except Exception as e:
                logger.error(
                    "ingest_trigger_failed",
                    source_id=source_id,
                    error=str(e),
                )
                results["errors"].append({"source_id": source_id, "error": str(e)})

    await redis_client.aclose()
    await engine.dispose()

    logger.info(
        "ingest_all_sources_complete",
        triggered=len(results["triggered"]),
        skipped=len(results["skipped"]),
        locked=len(results["locked"]),
        errors=len(results["errors"]),
    )
    return results


@app.task(
    name="govnotify.tasks.ingest_tasks.ingest_single_source",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def ingest_single_source(self, source_id: str):
    """
    Fetch new documents from a single source.
    Uses Redis distributed lock to prevent concurrent runs for the same source (§9: lock:source:{source_id}).
    """
    return _run_async(_ingest_single_source_async(self, source_id))


async def _ingest_single_source_async(task, source_id: str):
    """Async implementation - fetch, process, and store documents."""
    import redis.asyncio as autoredis
    import gc
    from sqlalchemy import select

    from govnotify.config import get_settings
    from govnotify.processing.pipeline import ProcessingPipeline
    from govnotify.sources.registry import SourceRegistry
    from govnotify.storage.postgres import (
        DocumentORM,
        IngestLogORM,
        SourceORM,
        get_engine,
        get_session_factory,
    )

    settings = get_settings()
    lock_key = f"lock:source:{source_id}"

    # Acquire Redis distributed lock (60 min TTL)
    redis_client = autoredis.from_url(settings.redis_url)
    lock = redis_client.lock(lock_key, timeout=3600)

    if not await lock.acquire(blocking=False):
        logger.warning(
            "ingest_skipped_locked",
            source_id=source_id,
        )
        await redis_client.aclose()
        return {"source_id": source_id, "status": "locked", "documents_new": 0}

    engine = get_engine()
    session_factory = get_session_factory(engine)

    ingest_start_time = get_utc_now()
    ingest_log = IngestLogORM(
        source_id=source_id,
        started_at=ingest_start_time,
        status="running",
    )

    try:
        source = SourceRegistry.get(source_id)
        pipeline = ProcessingPipeline(skip_embeddings=True, enable_llm=settings.enable_llm)
        
        fetched_count = 0
        new_count = 0
        dup_count = 0
        error_details = []

        async with session_factory() as session:
            # Create ingest log
            session.add(ingest_log)
            await session.flush()

            # Optimization: Set callback to allow source to check for duplicates before expensive OCR
            source.is_duplicate_callback = lambda doc: pipeline.check_duplicate(doc, session=session)

            # Get last fetch time from DB
            source_orm = await session.get(SourceORM, source_id)
            since = source_orm.last_fetched_at if source_orm else None

            # Fetch and process documents one by one (Streaming)
            logger.info("ingest_start_streaming", source_id=source_id)
            async for raw_doc in source.fetch(since=since):
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
                            summary_hindi=getattr(doc, "summary_hindi", ""),
                            categories=[c.value for c in doc.categories],
                            primary_category=doc.primary_category.value if doc.primary_category else None,
                            regions=doc.regions,
                            departments=doc.departments,
                            impact_tier=getattr(doc, "impact_tier", "Medium"),
                            affected_audience=getattr(doc, "affected_audience", []),
                            ingested_at=get_utc_now(),
                            entities=getattr(doc, "entities", {}),
                            language=doc.language,
                            content_hash=doc.content_hash,
                            is_duplicate=False,
                            confidence_score=doc.confidence_score,
                        )
                        session.add(doc_orm)
                        new_count += 1
                        
                        # Commit periodically or after each doc to keep memory low and progress visible
                        if new_count % 5 == 0:
                            await session.commit()
                            gc.collect()

                except Exception as doc_exc:
                    logger.error("ingest_doc_processing_failed", source_id=source_id, error=str(doc_exc))
                    error_details.append(str(doc_exc))

            # Update last_fetched_at to when this job started
            if source_orm:
                source_orm.last_fetched_at = ingest_start_time

            ingest_log.items_fetched = fetched_count
            ingest_log.items_new = new_count
            ingest_log.items_duplicate = dup_count
            ingest_log.errors = len(error_details)
            ingest_log.error_details = error_details[:20]
            ingest_log.status = "completed"
            ingest_log.completed_at = get_utc_now()

            await session.commit()
            gc.collect()

            logger.info(
                "ingest_complete",
                source_id=source_id,
                fetched=fetched_count,
                new=new_count,
                duplicates=dup_count,
                errors=len(error_details),
            )

            return {
                "source_id": source_id,
                "status": "completed",
                "documents_fetched": fetched_count,
                "documents_new": new_count,
                "documents_duplicate": dup_count,
                "errors": len(error_details),
            }

    except Exception as e:
        logger.error("ingest_failed", source_id=source_id, error=str(e))
        
        # Update ingest log on failure
        try:
            async with session_factory() as session:
                session.add(ingest_log) # Ensure it's tracked
                ingest_log.status = "failed"
                ingest_log.completed_at = get_utc_now()
                ingest_log.error_message = str(e)
                ingest_log.error_details = [str(e)]
                await session.commit()
        except Exception:
            pass

        raise task.retry(exc=e)

    finally:
        try:
            await lock.release()
        except Exception:
            pass
        await redis_client.aclose()
        await engine.dispose()
