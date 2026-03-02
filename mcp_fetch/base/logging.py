from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


def _level_from_str(level: Optional[str]) -> int:
    if not level:
        return logging.INFO
    upper = str(level).strip().upper()
    return {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }.get(upper, logging.INFO)


def configure_logging(*, level: Optional[str] = None) -> None:
    log_level = _level_from_str(level or os.environ.get("MCP_FETCH_LOG_LEVEL"))

    # Ensure log directory exists
    log_dir = Path(".fetch/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers = [
        logging.StreamHandler(sys.stderr),
        TimedRotatingFileHandler(
            filename=log_dir / "mcp-fetch.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        ),
    ]

    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    for noisy in ("fastmcp", "httpx", "playwright", "asyncio", "anyio"):
        logger = logging.getLogger(noisy)
        logger.setLevel(max(log_level, logging.WARNING))
        logger.propagate = False
