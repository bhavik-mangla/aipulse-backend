from fastapi import APIRouter, Depends
import structlog

from govnotify.api.deps import get_redis
from govnotify.storage.redis_store import RedisStore

router = APIRouter()
logger = structlog.get_logger(__name__)

@router.post("/visit")
async def track_visit(
    redis: RedisStore = Depends(get_redis)
):
    """Increment the global visitor count."""
    count = await redis.increment_visitor_count()
    logger.info("visitor_tracked", count=count)
    return {"status": "ok", "total_visits": count}

@router.get("/visits")
async def get_visits(
    redis: RedisStore = Depends(get_redis)
):
    """Get the total visitor count."""
    count = await redis.get_visitor_count()
    return {"total_visits": count}
