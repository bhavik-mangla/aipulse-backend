"""
LLM access with multi-key load balancing and fallback.

Two providers:

- "gemini" (default) spreads calls across every configured key and falls back
  down a chain of models when one is rate limited. The free tier is the
  binding constraint on how many sources the pipeline can carry.
- "local" talks to an OpenAI-compatible server on your own machine - Ollama,
  LM Studio or llama.cpp. It needs no API key and no quota, which is what
  makes the pipeline runnable by anyone who clones the repository.

The router is built lazily on first use. It used to be constructed at import
time, which meant importing anything under processing/ opened Redis
connections and read settings, including inside the API process that never
calls an LLM at all.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from litellm import Router

from govnotify.config import get_settings

logger = logging.getLogger(__name__)

# Google AI Studio keys all carry this prefix; anything else in the
# comma-separated list is a typo rather than a key.
GEMINI_KEY_PREFIX = "AIzaSy"

# Hosted models in fallback order. The first entry is the entry point and the
# rest are tried in order when it is unavailable or rate limited.
#
# Free-tier limits differ sharply between tiers, so the high-RPD models come
# first and the low-RPD Flash models act as a reserve.
GEMINI_MODELS = [
    {"name": "gemma-4-31b", "model": "gemini/gemma-4-31b-it", "rpm": 15, "rpd": 1500},
    {"name": "gemma-4-26b", "model": "gemini/gemma-4-26b-a4b-it", "rpm": 15, "rpd": 1500},
    {"name": "gemini-3.1-flash-lite", "model": "gemini/gemini-3.1-flash-lite", "rpm": 15, "rpd": 500},
    {"name": "gemini-2.5-flash-lite", "model": "gemini/gemini-2.5-flash-lite", "rpm": 10, "rpd": 20},
    {"name": "gemini-2.5-flash", "model": "gemini/gemini-2.5-flash", "rpm": 5, "rpd": 20},
]

LOCAL_MODEL_NAME = "local"

_router: Router | None = None
_entry_model: str | None = None


def get_gemini_keys() -> list[str]:
    """Parse the comma-separated Gemini API keys from settings."""
    keys = get_settings().gemini_api_key or ""
    return [k.strip() for k in keys.split(",") if k.strip().startswith(GEMINI_KEY_PREFIX)]


def _local_model_list(settings) -> list[dict[str, Any]]:
    """
    One entry pointing at a local OpenAI-compatible server.

    Ollama exposes its OpenAI-compatible API under /v1, and litellm's
    "openai/" prefix speaks that protocol. api_key is required by the client
    but ignored by the server.
    """
    base_url = settings.local_llm_base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    return [
        {
            "model_name": LOCAL_MODEL_NAME,
            "litellm_params": {
                "model": f"openai/{settings.local_llm_model}",
                "api_base": base_url,
                "api_key": "not-needed",
            },
        }
    ]


def _gemini_model_list(keys: list[str]) -> list[dict[str, Any]]:
    """Every model crossed with every key, so the router can spread load."""
    return [
        {
            "model_name": spec["name"],
            "litellm_params": {
                "model": spec["model"],
                "api_key": key,
                "rpm": spec["rpm"],
                "rpd": spec["rpd"],
            },
        }
        for spec in GEMINI_MODELS
        for key in keys
    ]


def build_router() -> tuple[Optional[Router], Optional[str]]:
    """Construct the router and the model name to enter it through."""
    settings = get_settings()

    if settings.use_local_llm:
        logger.info(
            "Using local LLM %s at %s",
            settings.local_llm_model,
            settings.local_llm_base_url,
        )
        return Router(model_list=_local_model_list(settings), num_retries=1), LOCAL_MODEL_NAME

    keys = get_gemini_keys()
    if not keys:
        logger.warning(
            "No Gemini API keys configured. Set GEMINI_API_KEY, or set "
            "LLM_PROVIDER=local to run against a local model instead."
        )
        return None, None

    return (
        Router(
            model_list=_gemini_model_list(keys),
            routing_strategy="simple-shuffle",
            num_retries=2,
        ),
        GEMINI_MODELS[0]["name"],
    )


def get_router() -> tuple[Optional[Router], Optional[str]]:
    """Lazily build the router once per process."""
    global _router, _entry_model
    if _router is None and _entry_model is None:
        _router, _entry_model = build_router()
    return _router, _entry_model


def reset_router() -> None:
    """Drop the cached router, so tests can switch providers."""
    global _router, _entry_model
    _router, _entry_model = None, None


def _extract_content(response) -> Optional[str]:
    """
    Pull the text out of a completion.

    Reasoning models put their answer in reasoning_content or thinking_blocks
    rather than content, and local models vary, so check each in turn.
    """
    if not response or not getattr(response, "choices", None):
        return None

    message = getattr(response.choices[0], "message", None)
    if message is None:
        return None

    for attr in ("content", "reasoning_content"):
        value = getattr(message, attr, None)
        if value:
            return str(value).strip()

    blocks = getattr(message, "thinking_blocks", None)
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict):
                value = block.get("text") or block.get("thinking")
                if value:
                    return str(value).strip()

    return None


async def get_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    json_mode: bool = False,
    **kwargs: Any,
) -> Optional[str]:
    """
    Run a completion, returning None rather than raising on failure.

    Set json_mode when the caller needs parseable JSON back. It matters most
    for local models: a reasoning model asked politely for JSON will happily
    return several paragraphs of deliberation instead, and small models drift
    out of the format. Constraining the response format removes the guesswork.
    """
    settings = get_settings()
    if not settings.enable_llm:
        logger.info("LLM disabled in settings, skipping call.")
        return None

    router, entry_model = get_router()
    if router is None or entry_model is None:
        return None

    # Locally there is one model and nothing to fall back to.
    fallbacks = None if settings.use_local_llm else [m["name"] for m in GEMINI_MODELS[1:]]

    if json_mode:
        kwargs.setdefault("response_format", {"type": "json_object"})

    try:
        response = await router.acompletion(
            model=entry_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **({"fallbacks": fallbacks} if fallbacks else {}),
            **kwargs,
        )
    except Exception as exc:
        logger.error("LLM completion failed: %s", exc)
        return None

    content = _extract_content(response)
    if not content:
        logger.warning("LLM returned no usable content (model=%s)", getattr(response, "model", "?"))
    return content
