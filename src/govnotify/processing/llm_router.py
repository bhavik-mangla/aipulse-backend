
import logging
from typing import Any, Optional
import litellm
from litellm import Router
from govnotify.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# LiteLLM Router Configuration
# Priority-based fallback: Gemma 4 31B -> Gemma 4 26B -> Gemma 3 27B
model_list = [
    {
        "model_name": "gemma-4-31b",
        "litellm_params": {
            "model": "gemini/gemma-4-31b-it",
            "api_key": settings.gemini_api_key,
            "rpm": 15,
            "rpd": 1500,
        },
    },
    {
        "model_name": "gemma-4-26b",
        "litellm_params": {
            "model": "gemini/gemma-4-26b-a4b-it",
            "api_key": settings.gemini_api_key,
            "rpm": 15,
            "rpd": 1500,
        },
    },
    {
        "model_name": "gemma-3-27b",
        "litellm_params": {
            "model": "gemini/gemma-3-27b-it",
            "api_key": settings.gemini_api_key,
            "rpm": 30,
            "rpd": 14400,
        },
    }
]

# Initialize Router with Redis for cross-restart rate limit tracking
# The project already uses Redis for Celery/Caching
llm_router = Router(
    model_list=model_list,
    routing_strategy="simple-shuffle",
    set_verbose=False,
    num_retries=3,
    retry_after=5,
    redis_url=settings.redis_url,
)

async def get_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 400,
    **kwargs: Any
) -> Optional[str]:
    """
    Get completion using the router with automatic fallback and RPM/RPD tracking.
    """
    if not settings.enable_llm:
        logger.info("LLM disabled in settings, skipping call.")
        return None

    try:
        # Strictly follow the fallback chain user requested
        response = await llm_router.acompletion(
            model="gemma-4-31b", # Primary
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            fallbacks=["gemma-4-26b", "gemma-3-27b"],
            **kwargs
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"LLM completion failed across all fallbacks: {str(e)}")
        return None
