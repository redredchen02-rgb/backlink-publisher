"""Optional structlog integration for backlink-publisher.

Call ``configure_structlog()`` at application startup (Flask ``create_app()``
or CLI entry point) to enable structlog-based structured logging alongside
the existing ``PipelineLogger``.  This module is **opt-in** — it is never
imported eagerly by any production code path.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

# Reuse the sensitive-key set from PipelineLogger so both loggers redact
# the same fields.
from backlink_publisher._util.logger import _SENSITIVE_KEYS, _REDACTED


def _redact_processor(
    logger: structlog.types.FilteringBoundLogger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Redact sensitive values in the event dict before rendering.

    Mirrors the behaviour of ``PipelineLogger._redact_in_place`` — any key
    whose name matches a casefolded sensitive key has its value replaced.
    """

    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_REDACTED if isinstance(k, str) and k.casefold() in _SENSITIVE_KEYS else _redact(v))
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return type(value)(_redact(v) for v in value)
        return value

    return cast(dict[str, Any], _redact(event_dict))


def configure_structlog(
    log_level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure structlog for structured logging to stderr.

    Parameters
    ----------
    log_level:
        Minimum log level (default ``INFO``).
    json_format:
        If ``True`` (default), output JSON.  If ``False``, output coloured
        console-friendly format.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.dev.set_exc_info,
        cast(structlog.types.Processor, _redact_processor),
    ]

    if json_format:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging into structlog so existing ``logging.getLogger()``
    # calls also go through structlog's processors (redaction, format, etc.).
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    # Remove default handlers to avoid duplicate output
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> Any:
    """Get a structlog logger, configured after ``configure_structlog()``.

    Shortcut for ``structlog.get_logger(name)``.
    """
    return structlog.get_logger(name)
