"""
Processing pipeline tasks.
Standalone Celery tasks for running the NLP processing pipeline on
raw documents outside of the ingestion flow (e.g., reprocessing, manual triggers from admin API).
"""
from __future__ import annotations

import asyncio
from datetime import datetime

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
    bind=True,
    name="govnotify.tasks.process_tasks.process_document",
    max_retries=2,
    default_retry_delay=30,
)
def process_document(self, document_id: str):
    """
    Reprocess a single document through the NLP pipeline.
    Used for manual reprocessing via admin API. Fetches the raw content from PostgreSQL, runs through enricher + chunker again.
    """
    return _run_async(_process_document_async(self, document_id))


async def _process_document_async(task, document_id: str):
    """Async implementation of process_document."""
    from sqlalchemy import select
    from govnotify.processing.pipeline import ProcessingPipeline
    from govnotify.models.source import RawDocument
    from govnotify.storage.postgres import (
        DocumentORM,
        get_engine,
        get_session_factory,
    )

    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    try:
        async with session_factory() as session:
            doc_orm = await session.get(DocumentORM, document_id)
            if not doc_orm:
                logger.warning("process_document_not_found", document_id=document_id)
                return {"document_id": document_id, "status": "not_found"}

            # Reconstruct RawDocument from stored data
            raw_doc = RawDocument(
                source_id=doc_orm.source_id,
                source_url=doc_orm.source_url,
                fetch_url=doc_orm.source_url,
                title=doc_orm.title,
                raw_content=doc_orm.clean_text or "",
                content_type="text/plain",
                fetched_at=get_utc_now(),
                language=doc_orm.language or "en",
            )
            raw_doc.compute_content_hash()

            pipeline = ProcessingPipeline(skip_embeddings=True)
            result = await pipeline.process(raw_doc)

            if result.error:
                return {
                    "document_id": document_id,
                    "status": "error",
                    "error": result.error,
                }

            if result.document:
                doc = result.document
                doc_orm.summary = doc.summary
                doc_orm.categories = [c.value for c in doc.categories]
                doc_orm.primary_category = (
                    doc.primary_category.value if doc.primary_category else None
                )
                doc_orm.regions = doc.regions
                doc_orm.departments = doc.departments
                doc_orm.processed_at = get_utc_now()
                await session.commit()

            logger.info("process_document_complete", document_id=document_id)
            return {"document_id": document_id, "status": "completed"}

    except Exception as e:
        logger.error("process_document_failed", document_id=document_id, error=str(e))
        raise task.retry(exc=e)
    finally:
        await engine.dispose()


@app.task(
    bind=True,
    name="govnotify.tasks.process_tasks.reprocess_batch",
    max_retries=1,
    default_retry_delay=120,
)
def reprocess_batch(self, document_ids: list[str]):
    """Reprocess a batch of documents. Fans out to individual tasks."""
    results = {"triggered": [], "errors": []}
    
    for doc_id in document_ids:
        try:
            process_document.delay(doc_id)
            results["triggered"].append(doc_id)
        except Exception as e:
            results["errors"].append({"document_id": doc_id, "error": str(e)})

    logger.info(
        "reprocess_batch_triggered",
        count=len(results["triggered"]),
        errors=len(results["errors"]),
    )
    return results
