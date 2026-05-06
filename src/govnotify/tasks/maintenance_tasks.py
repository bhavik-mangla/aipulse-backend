"""
Maintenance tasks - cleanup, health checks, data retention.
Per §24.5:
- Documents retained 30 days
- Category digests retained 30 days
- User digests retained 30 days
- Ingest logs retained 30 days

Scheduled:
- run_maintenance: daily at 2:00 AM IST (20:30 UTC)
- check_source_health: every 15 minutes
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import structlog
from govnotify.utils.time import get_utc_now
from sqlalchemy import delete

from govnotify.tasks.celery_app import app
from govnotify.storage.postgres import (
    CategoryDigestORM,
    DigestORM,
    DocumentORM,
    IngestLogORM,
    get_engine,
    get_session_factory,
)

logger = structlog.get_logger(__name__)

# Data retention period (§24.5)
RETENTION_DAYS = 120


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
    name="govnotify.tasks.maintenance_tasks.run_maintenance",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def run_maintenance(self):
    """
    Daily maintenance: purge expired data per §24.5 retention policy.
    Runs at 20:30 UTC (2:00 AM IST).
    """
    return _run_async(_run_maintenance_async(self))


async def _run_maintenance_async(task):
    """Async implementation - purge old records from all tables."""
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    cutoff = get_utc_now() - timedelta(days=RETENTION_DAYS)
    cutoff_date_str = cutoff.strftime("%Y-%m-%d")

    results = {
        "documents_deleted": 0,
        "category_digests_deleted": 0,
        "user_digests_deleted": 0,
        "ingest_logs_deleted": 0,
    }

    try:
        async with session_factory() as session:
            # 1. Purge old documents
            stmt = delete(DocumentORM).where(DocumentORM.ingested_at < cutoff)
            result = await session.execute(stmt)
            results["documents_deleted"] = result.rowcount

            # 2. Purge old category digests
            stmt = delete(CategoryDigestORM).where(CategoryDigestORM.date < cutoff_date_str)
            result = await session.execute(stmt)
            results["category_digests_deleted"] = result.rowcount

            # 3. Purge old user digests
            stmt = delete(DigestORM).where(DigestORM.date < cutoff_date_str)
            result = await session.execute(stmt)
            results["user_digests_deleted"] = result.rowcount

            # 4. Purge old ingest logs
            stmt = delete(IngestLogORM).where(IngestLogORM.started_at < cutoff)
            result = await session.execute(stmt)
            results["ingest_logs_deleted"] = result.rowcount

            await session.commit()

        logger.info(
            "maintenance_complete",
            cutoff=cutoff.isoformat(),
            **results,
        )
        return {
            "status": "completed",
            "cutoff": cutoff.isoformat(),
            **results,
        }

    except Exception as e:
        logger.error("maintenance_failed", error=str(e))
        raise task.retry(exc=e)
    finally:
        await engine.dispose()


@app.task(
    name="govnotify.tasks.maintenance_tasks.check_source_health",
    bind=True,
    max_retries=0,
)
def check_source_health(self):
    """
    Health-check all registered sources every 15 minutes.
    Calls each source's health_check() method and logs the result.
    Does NOT disable sources automatically - that's an admin decision.
    """
    return _run_async(_check_source_health_async())


async def _check_source_health_async():
    """Async implementation - run health checks on all sources."""
    import redis.asyncio as autoredis
    from govnotify.config import get_settings
    from govnotify.sources.registry import SourceRegistry

    settings = get_settings()
    sources = SourceRegistry.all()
    
    results = {
        "healthy": [],
        "unhealthy": [],
        "errors": [],
    }

    for source in sources:
        try:
            is_healthy = await source.health_check()
            if is_healthy:
                results["healthy"].append(source.source_id)
            else:
                results["unhealthy"].append(source.source_id)
        except Exception as e:
            results["errors"].append({"source_id": source.source_id, "error": str(e)})

    # Store health snapshot in Redis for admin dashboard
    try:
        redis_client = autoredis.from_url(settings.redis_url)
        await redis_client.setex(
            "health:sources",
            900,  # 15 min TTL
            json.dumps(results),
        )
        await redis_client.aclose()
    except Exception:
        # Redis failure shouldn't break health checks
        pass

    logger.info(
        "source_health_check_complete",
        healthy=len(results["healthy"]),
        unhealthy=len(results["unhealthy"]),
        errors=len(results["errors"]),
    )
    return results
