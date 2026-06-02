
import logging
from typing import Any, Optional
import litellm
from litellm import Router
from govnotify.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

def get_gemini_keys() -> list[str]:
    """Parse comma-separated Gemini API keys from settings."""
    keys_str = settings.gemini_api_key or ""
    # Filter only valid-looking Google AI keys (starting with AIzaSy)
    return [k.strip() for k in keys_str.split(",") if k.strip().startswith("AIzaSy")]

# Model priority and limits based on user reference:
# 1. Gemma 4 31B (Best, high RPD)
# 2. Gemma 4 26B (High quality, high RPD)
# 3. Gemini 3.1 Flash Lite (High capacity RPD 500)
# 4. Gemini 2.5 Flash / 3.5 Flash / 3 Flash / 2.5 Flash Lite (RPD 20 each)

def create_model_list() -> list[dict[str, Any]]:
    keys = get_gemini_keys()
    if not keys:
        logger.warning("No Gemini API keys found in settings.")
        return []

    models = []
    
    # Priority 1 & 2: Gemma 4 series (RPD 1500, RPM 15)
    for model_name, litellm_name in [
        ("gemma-4-31b", "gemini/gemma-4-31b-it"),
        ("gemma-4-26b", "gemini/gemma-4-26b-a4b-it")
    ]:
        for i, key in enumerate(keys):
            models.append({
                "model_name": model_name,
                "litellm_params": {
                    "model": litellm_name,
                    "api_key": key,
                    "rpm": 15,
                    "rpd": 1500,
                },
            })

    # Priority 3: Gemini 3.1 Flash Lite (RPD 500, RPM 15)
    for i, key in enumerate(keys):
        models.append({
            "model_name": "gemini-3.1-flash-lite",
            "litellm_params": {
                "model": "gemini/gemini-3.1-flash-lite",
                "api_key": key,
                "rpm": 15,
                "rpd": 500,
            },
        })

    # Priority 4: Flash series (RPD 20, RPM 5-10)
    flash_models = [
        ("gemini-2.5-flash-lite", "gemini/gemini-2.5-flash-lite", 10),
        ("gemini-2.5-flash", "gemini/gemini-2.5-flash", 5),
        ("gemini-3.5-flash", "gemini/gemini-3.5-flash", 5),
        ("gemini-3-flash", "gemini/gemini-3-flash", 5),
    ]
    for model_name, litellm_name, rpm in flash_models:
        for i, key in enumerate(keys):
            models.append({
                "model_name": model_name,
                "litellm_params": {
                    "model": litellm_name,
                    "api_key": key,
                    "rpm": rpm,
                    "rpd": 20,
                },
            })
            
    return models

# Initialize Router with Redis for cross-restart rate limit tracking
# Handle Redis connectivity gracefully for local development
_redis_url = settings.redis_url
if "redis://redis" in _redis_url:
    import socket
    try:
        socket.gethostbyname("redis")
    except socket.gaierror:
        logger.info("Redis host not found, falling back to localhost for Redis.")
        _redis_url = _redis_url.replace("redis://redis", "redis://localhost")

llm_router = Router(
    model_list=create_model_list(),
    routing_strategy="simple-shuffle",
    set_verbose=False,
    num_retries=3,
    retry_after=2,
    redis_url=_redis_url,
)

async def get_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    **kwargs: Any
) -> Optional[str]:
    """
    Get completion using the router with multi-key load balancing and extensive fallback.
    Supports models that return content in reasoning_content or thinking_blocks.
    """
    if not settings.enable_llm:
        logger.info("LLM disabled in settings, skipping call.")
        return None

    # Fallback chain across all supported models
    fallbacks = [
        "gemma-4-26b",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-3-flash",
        "gemini-1.5-flash" # Added as ultimate fallback
    ]

    try:
        response = await llm_router.acompletion(
            model="gemma-4-31b", # Primary entry point
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            fallbacks=fallbacks,
            **kwargs
        )
        
        # Log which model was actually used
        used_model = response.get("model", "unknown")
        logger.info(f"LLM used model: {used_model}")

        if response and response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            message = getattr(choice, 'message', None)
            if message:
                # 1. Standard content
                content = getattr(message, 'content', None)
                
                # 2. Fallback to reasoning_content (newer instruction models)
                if not content:
                    content = getattr(message, 'reasoning_content', None)
                
                # 3. Fallback to thinking_blocks
                if not content:
                    thinking = getattr(message, 'thinking_blocks', None)
                    if thinking and isinstance(thinking, list) and len(thinking) > 0:
                        for block in thinking:
                            if isinstance(block, dict):
                                # Prioritize 'text' over 'thinking'
                                content = block.get('text') or block.get('thinking')
                                if content:
                                    break
                
                # 4. Fallback to message string representation or data if content is still None
                if not content:
                    try:
                        if isinstance(message, dict):
                            content = message.get("content")
                        else:
                            content = getattr(message, "content", None)
                    except:
                        pass

                if content:
                    return str(content).strip()
        
        logger.warning(f"LLM returned empty response choices or null content. Model: {used_model}")
        return None
    except Exception as e:
        logger.error(f"LLM completion failed across all fallbacks: {str(e)}")
        return None
