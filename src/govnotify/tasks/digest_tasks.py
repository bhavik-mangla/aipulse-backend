"""
Digest generation and delivery tasks.
Phase 1: generate_all_category_digests - 6:30 AM IST (1:00 AM UTC)
- Zero LLM calls. Pure data grouping and category summary assembly.

Phase 2: assemble_and_send_user_digests - 7:00 AM IST (1:30 AM UTC)
- Zero LLM calls. Pure data assembly + delivery fan-out.

Per §24.8 retry policy:
- Email: retry once after 5 minutes, then skip
- Telegram: no retry on permanent errors (blocked/forbidden)
- Never retry more than once per digest per channel
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta

import structlog
from govnotify.utils.time import get_utc_now, get_today_str
from sqlalchemy import select

from govnotify.tasks.celery_app import app
from govnotify.config import get_settings
from govnotify.digests.assembler import UserDigestAssembler
from govnotify.digests.category_digest import CategoryDigestGenerator
from govnotify.constants import NoticeCategory
from govnotify.models.document import ProcessedDocument
from govnotify.models.notification import CategoryDigest, UserDigest
from govnotify.models.user import (
    DeliveryChannel,
    DigestFrequency,
    UserPreferences,
    UserProfile,
)
from govnotify.storage.postgres import (
    CategoryDigestORM,
    DigestORM,
    DocumentORM,
    UserORM,
    get_engine,
    get_session_factory,
)

logger = structlog.get_logger(__name__)

# Batch size for user digest assembly (§11.2)
USER_BATCH_SIZE = 500


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


# --- Phase 1: Category Digest Generation ---

@app.task(
    bind=True,
    name="govnotify.tasks.digest_tasks.generate_all_category_digests",
    max_retries=1,
    default_retry_delay=300,
)
def generate_all_category_digests(self, date_str: str | None = None):
    """
    Generate CategoryDigests for all 17 categories.
    Runs at 1:00 AM UTC (6:30 AM IST).
    Uses a Redis lock to prevent duplicate generation runs.
    """
    return _run_async(_generate_all_category_digests_async(self, date_str))


async def _generate_all_category_digests_async(task, date_str: str | None):
    """Async implementation - generate + cache + store all category digests."""
    import redis.asyncio as autoredis
    from govnotify.config import get_settings

    settings = get_settings()
    today = date_str or get_today_str()
    lock_key = f"lock:digest_generation:{today}"

    redis_client = autoredis.from_url(settings.redis_url)
    lock = redis_client.lock(lock_key, timeout=1800)  # 30 min TTL

    if not await lock.acquire(blocking=False):
        logger.warning("digest_generation_locked", date=today)
        await redis_client.aclose()
        return {"date": today, "status": "locked"}

    try:
        engine = get_engine()
        session_factory = get_session_factory(engine)
        async with session_factory() as session:
            # Query documents from the last 24 hours
            now = get_utc_now()
            start_time = now - timedelta(hours=24)
            
            stmt = (
                select(DocumentORM)
                .where(DocumentORM.ingested_at >= start_time)
                .where(DocumentORM.is_duplicate == False)  # noqa: E712
                .order_by(DocumentORM.ingested_at.desc())
            )
            result = await session.execute(stmt)
            doc_orms = result.scalars().all()

            # Convert ORM -> ProcessedDocument for the generator
            processed_docs = []
            for d in doc_orms:
                pd = ProcessedDocument(
                    id=str(d.id),
                    source_id=d.source_id,
                    source_url=d.source_url,
                    title=d.title,
                    clean_text=d.clean_text or "",
                    summary=d.summary or "",
                    summary_hindi=d.summary_hindi or "",
                    categories=[
                        NoticeCategory(c)
                        for c in (d.categories or [])
                        if c in NoticeCategory.__members__.values()
                    ],
                    primary_category=(
                        NoticeCategory(d.primary_category)
                        if d.primary_category and d.primary_category in NoticeCategory.__members__.values()
                        else NoticeCategory.OTHER
                    ),
                    regions=d.regions or [],
                    departments=d.departments or [],
                    impact_tier=d.impact_tier or "Medium",
                    affected_audience=d.affected_audience or [],
                    ingested_at=d.ingested_at,
                    language=d.language or "en",
                    content_hash=d.content_hash or "",
                    confidence_score=d.confidence_score or 0.0,
                )
                processed_docs.append(pd)

            logger.info(
                "digest_generation_start",
                date=today,
                total_documents=len(processed_docs),
            )

            # Generate all category digests via LLM
            generator = CategoryDigestGenerator()
            category_digests = await generator.generate_all(
                date_str=today,
                documents=processed_docs,
            )

            # Store in PostgreSQL + cache in Redis
            stored = 0
            for cd in category_digests:
                # Upsert into PG
                stmt = select(CategoryDigestORM).where(
                    CategoryDigestORM.category == cd.category.value,
                    CategoryDigestORM.date == today,
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()

                if existing:
                    existing.items = [item.model_dump(mode="json") for item in cd.items]
                    existing.summary_text = cd.summary_text
                    existing.summary_hindi = cd.summary_hindi
                    existing.item_count = cd.item_count
                    existing.has_updates = cd.has_updates
                    existing.generated_at = cd.generated_at
                    existing.llm_model_used = cd.model_used
                    existing.llm_cost_usd = cd.llm_cost_usd
                else:
                    orm = CategoryDigestORM(
                        id=cd.id,
                        category=cd.category.value,
                        date=today,
                        items=[item.model_dump(mode="json") for item in cd.items],
                        summary_text=cd.summary_text,
                        summary_hindi=cd.summary_hindi,
                        item_count=cd.item_count,
                        has_updates=cd.has_updates,
                        generated_at=cd.generated_at,
                        llm_model_used=cd.model_used,
                        llm_cost_usd=cd.llm_cost_usd,
                    )
                    session.add(orm)
                
                # Cache in Redis (48h TTL)
                cache_key = f"digest:category:{cd.category.value}:{today}"
                await redis_client.set(
                    cache_key, cd.model_dump_json(), ex=172800
                )
                stored += 1

            await session.commit()
            logger.info(
                "digest_generation_complete",
                date=today,
                categories_processed=stored,
                total_documents=len(processed_docs),
            )
            return {
                "date": today,
                "status": "completed",
                "categories_generated": stored,
                "total_documents": len(processed_docs),
            }

    except Exception as e:
        logger.error("digest_generation_failed", date=today, error=str(e))
        raise task.retry(exc=e)
    finally:
        try:
            await lock.release()
        except Exception:
            pass
        await redis_client.aclose()
        await engine.dispose()


# --- Phase 2: User Digest Assembly & Delivery ---

@app.task(
    bind=True,
    name="govnotify.tasks.digest_tasks.assemble_and_send_user_digests",
    max_retries=1,
    default_retry_delay=300,
)
def assemble_and_send_user_digests(self, date_str: str | None = None):
    """
    Assemble per-user digests and fan out delivery tasks.
    Runs at 1:30 AM UTC (7:00 AM IST), after category digests are ready.
    Processes users in batches of 500.
    """
    return _run_async(_assemble_and_send_user_digests_async(self, date_str))


async def _assemble_and_send_user_digests_async(task, date_str: str | None):
    """Async implementation - load category digests, assemble user digests, fan out delivery."""
    import redis.asyncio as autoredis
    from govnotify.config import get_settings

    settings = get_settings()
    today = date_str or get_today_str()
    engine = get_engine()
    session_factory = get_session_factory(engine)
    redis_client = autoredis.from_url(settings.redis_url)

    try:
        # 1. Load pre-generated category digests (from Redis cache, fallback PG)
        category_digests: dict[NoticeCategory, CategoryDigest] = {}
        for cat in NoticeCategory:
            cache_key = f"digest:category:{cat.value}:{today}"
            cached = await redis_client.get(cache_key)
            if cached:
                category_digests[cat] = CategoryDigest.model_validate_json(cached)

        # Fallback: load from PG for any missing categories
        if len(category_digests) < len(NoticeCategory):
            async with session_factory() as session:
                missing_cats = [c for c in NoticeCategory if c not in category_digests]
                for cat in missing_cats:
                    stmt = select(CategoryDigestORM).where(
                        CategoryDigestORM.category == cat.value,
                        CategoryDigestORM.date == today,
                    )
                    result = await session.execute(stmt)
                    orm = result.scalar_one_or_none()
                    if orm:
                        cd = CategoryDigest(
                            id=str(orm.id),
                            category=NoticeCategory(orm.category),
                            date=orm.date,
                            items=orm.items or [],
                            summary_text=orm.summary_text or "",
                            summary_hindi=orm.summary_hindi or "",
                            item_count=orm.item_count or 0,
                            has_updates=orm.has_updates,
                            generated_at=orm.generated_at,
                        )
                        category_digests[cat] = cd

        logger.info(
            "user_digest_assembly_start",
            date=today,
            category_digests_available=len(category_digests),
        )

        # 2. Fetch active users in batches
        assembler = UserDigestAssembler()
        total_sent = 0
        offset = 0

        while True:
            async with session_factory() as session:
                stmt = (
                    select(UserORM)
                    .where(UserORM.is_active == True) # noqa: E712
                    .offset(offset)
                    .limit(USER_BATCH_SIZE)
                )
                result = await session.execute(stmt)
                user_orms = result.scalars().all()
                
                if not user_orms:
                    break

                # Convert ORM -> UserProfile
                users = []
                for u in user_orms:
                    prefs_data = u.preferences or {}
                    prefs = UserPreferences(**prefs_data)
                    
                    # Skip users who don't want daily digests
                    if prefs.digest_frequency != DigestFrequency.DAILY:
                        continue
                        
                    profile = UserProfile(
                        id=str(u.id),
                        email=u.email,
                        telegram_chat_id=u.telegram_chat_id,
                        name=u.name,
                        preferences=prefs,
                        is_active=u.is_active,
                    )
                    users.append(profile)

                # Assemble user digests (zero LLM calls)
                user_digests = assembler.assemble_batch(
                    users=users,
                    category_digests=category_digests,
                    date_str=today,
                )

                # Fan out delivery tasks for each user digest
                for ud in user_digests:
                    deliver_user_digest.delay(
                        user_digest_json=ud.model_dump_json(),
                        date_str=today,
                    )
                    total_sent += 1

                offset += USER_BATCH_SIZE

        logger.info(
            "user_digest_assembly_complete",
            date=today,
            total_sent=total_sent,
        )
        return {"date": today, "status": "completed", "digests_queued": total_sent}

    except Exception as e:
        logger.error("user_digest_assembly_failed", date=today, error=str(e))
        raise task.retry(exc=e)
    finally:
        await redis_client.aclose()
        await engine.dispose()


@app.task(
    bind=True,
    name="govnotify.tasks.digest_tasks.deliver_user_digest",
    max_retries=1,
    default_retry_delay=300, # 5 min retry for email (§24.8)
)
def deliver_user_digest(self, user_digest_json: str, date_str: str):
    """
    Deliver a single user digest via configured channels.
    Retry policy per §24.8:
    - Email: retry once after 5 minutes
    - Telegram: no retry on permanent errors (blocked/forbidden)
    - Never retry more than once per digest per channel
    """
    return _run_async(_deliver_user_digest_async(self, user_digest_json, date_str))


async def _deliver_user_digest_async(task, user_digest_json: str, date_str: str):
    """Async implementation - send via delivery channel + record result."""
    from govnotify.delivery import ChannelRegistry
    from govnotify.models.notification import UserDigest
    from govnotify.models.user import UserProfile, UserPreferences

    user_digest = UserDigest.model_validate_json(user_digest_json)
    channel_type = user_digest.delivery_channel
    
    engine = get_engine()
    session_factory = get_session_factory(engine)
    
    try:
        # Look up user profile from DB
        async with session_factory() as session:
            user_orm = await session.get(UserORM, user_digest.user_id)
            if not user_orm:
                logger.warning("deliver_user_not_found", user_id=user_digest.user_id)
                return {"user_id": user_digest.user_id, "status": "user_not_found"}

            prefs_data = user_orm.preferences or {}
            user = UserProfile(
                id=str(user_orm.id),
                email=user_orm.email,
                telegram_chat_id=user_orm.telegram_chat_id,
                name=user_orm.name,
                is_active=user_orm.is_active,
                preferences=UserPreferences(**prefs_data),
            )

        # Get the delivery channel from registry
        channel = ChannelRegistry.get(channel_type)
        if not channel:
            logger.error("delivery_channel_not_found", channel=channel_type.value)
            return {"user_id": user.id, "status": "channel_not_found"}

        # Send!
        result = await channel.send(user, user_digest)

        # Record result in DB
        async with session_factory() as session:
            orm = DigestORM(
                id=user_digest.id,
                user_id=user.id,
                category_sections=[s.model_dump(mode="json") for s in user_digest.category_sections],
                delivery_channel=channel_type.value,
                date=date_str,
                total_items=user_digest.total_items,
                delivered=result.success,
                delivered_at=result.delivered_at,
                error_message=result.error_message,
            )
            session.add(orm)
            await session.commit()

        if not result.success:
            # Handle retries per §24.8
            if "PERMANENT" in (result.error_message or ""):
                logger.warning("delivery_failed_permanent", user_id=user.id, error=result.error_message)
            elif task and task.request.retries < task.max_retries:
                logger.info("delivery_retrying", user_id=user.id, channel=channel_type.value)
                raise task.retry(exc=Exception(result.error_message))

        return {"user_id": user.id, "status": "success" if result.success else "failed"}

    except Exception as e:
        logger.error("delivery_task_error", user_id=user_digest.user_id, error=str(e))
        if task and task.request.retries < task.max_retries:
            raise task.retry(exc=e)
        raise
