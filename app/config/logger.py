"""Shared logging setup for JARVIS.

Provides a single :func:`get_logger` helper that writes to both the console and
a rotating log file under ``logs/``.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import LOG_DIR, settings


_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger, creating handlers only once per name."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = getattr(logging, settings.log_level, logging.INFO)
    logger.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_DIR / "jarvis.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
