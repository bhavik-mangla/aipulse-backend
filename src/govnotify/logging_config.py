"""
Structured logging configuration for GovNotify.
Configures "structlog" with:
- Human-readable console output in development
- JSON rendering in production ("GOVNOTIFY_ENV=production")
- Automatic context binding (timestamp, log level, logger name)
- Correlation/request-ID propagation via "contextvars"

Call setup_logging() once at application startup - both the FastAPI entry point and the Celery worker entry point should call it.
"""
from __future__ import annotations

import logging
import os
import sys
from contextvars import ContextVar

import structlog

# --- Context vars for request / task correlation ---
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the current correlation / request ID (if set)."""
    return _correlation_id.get()


def set_correlation_id(cid: str) -> None:
    """Bind a correlation / request ID to the current context."""
    _correlation_id.set(cid)


def _add_correlation_id(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    """Structlog processor: inject correlation_id if present."""
    cid = _correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


# --- Public API ---

def setup_logging(env: str | None = None) -> None:
    """
    Configure structlog for the entire process.
    Args:
        env: "production" for JSON output, anything else for coloured console output.
             Defaults to the GOVNOTIFY_ENV environment variable (default: "development").
    """
    if env is None:
        env = os.getenv("GOVNOTIFY_ENV", "development")

    is_production = env == "production"

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_id,
    ]

    if is_production:
        # Production: JSON output to stdout
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Development: Pretty console output
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.NOTSET),
        cache_logger_on_first_use=True,
    )

    # Standard logging redirect (optional but recommended for libraries)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    
    # Silence some noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("amqp").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)

    structlog.get_logger(__name__).info("logging_setup_complete", env=env)
