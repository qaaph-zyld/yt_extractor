"""Logging configuration for ytmp3dl.

Provides a console handler (human-friendly, level driven by ``--verbose`` /
``--quiet``) and an optional rotating file handler (always DEBUG, for
post-mortems). yt-dlp's own logger is routed through ours so its output honours
the same handlers and levels instead of going straight to stdout/stderr.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "ytmp3dl"

# Rotating file handler sizing: keep a handful of modestly sized logs.
_FILE_MAX_BYTES = 5 * 1024 * 1024
_FILE_BACKUP_COUNT = 3


def get_logger() -> logging.Logger:
    """Return the package's root logger."""
    return logging.getLogger(LOGGER_NAME)


def setup_logging(
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """Configure and return the package logger.

    The logger itself is set to DEBUG so the file handler can capture
    everything; the console handler's level is what the user perceives.
    Idempotent: existing handlers are cleared so repeated calls (e.g. in tests)
    do not duplicate output.
    """
    logger = get_logger()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Clear any handlers from a previous configuration.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    if quiet:
        console_level = logging.WARNING
    elif verbose:
        console_level = logging.DEBUG
    else:
        console_level = logging.INFO

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(console)

    if log_file:
        path = Path(log_file)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=_FILE_MAX_BYTES,
            backupCount=_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s"
            )
        )
        logger.addHandler(file_handler)

    return logger


class YtdlpLoggerAdapter:
    """Adapter exposing the interface yt-dlp expects from a ``logger``.

    yt-dlp calls ``debug`` / ``info`` / ``warning`` / ``error`` on whatever is
    passed as its ``logger`` param. We forward those to a standard
    :class:`logging.Logger`, downgrading yt-dlp's chatty ``info``/``debug`` to
    DEBUG so the console stays readable (progress is reported separately via
    progress hooks).
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or get_logger().getChild("yt_dlp")

    def debug(self, msg: str) -> None:
        # yt-dlp prefixes debug lines with "[debug] "; everything else it sends
        # to debug() is really informational. Keep both at DEBUG on console.
        self._logger.debug(msg)

    def info(self, msg: str) -> None:
        self._logger.debug(msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        self._logger.error(msg)


__all__ = ["LOGGER_NAME", "YtdlpLoggerAdapter", "get_logger", "setup_logging"]