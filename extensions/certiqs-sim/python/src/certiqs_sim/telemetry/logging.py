"""structlog-based JSON logging setup.

Every service calls :func:`configure_logging` once at startup.  Logs are emitted
as JSON (Loki-compatible) with the service name, and per-request/per-window
context (run_id, epoch, settings_version) can be bound with :func:`bind_context`.

Per-logger levels are configured via ``module_levels`` (e.g.
``certiqs.engine=WARNING``) so high-frequency engine events do not flood stdout.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_CONFIGURED = False


def parse_module_levels(spec: str) -> dict[str, str]:
    levels: dict[str, str] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, level = part.split("=", 1)
        name = name.strip()
        level = level.strip().upper()
        if name and level:
            levels[name] = level
    return levels


def configure_logging(
    service: str = "certiqs",
    level: str = "INFO",
    json_logs: bool = True,
    module_levels: dict[str, str] | None = None,
) -> None:
    global _CONFIGURED

    log_level = getattr(logging, str(level).upper(), logging.INFO)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Root at the configured level so third-party loggers (httpx, asyncio, …)
    # do not flood output; per-module overrides below may still lower levels.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Default threshold for all certiqs loggers unless overridden below.
    logging.getLogger("certiqs").setLevel(log_level)
    for name, lvl in (module_levels or {}).items():
        logging.getLogger(name).setLevel(getattr(logging, str(lvl).upper(), log_level))

    # Bind the service name into the contextvars so every log line carries it.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service)
    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """Bind key/values into the logging context for the current execution scope."""
    structlog.contextvars.bind_contextvars(**kwargs)


__all__ = ["bind_context", "configure_logging", "get_logger", "parse_module_levels"]
