"""Logging for a stdio MCP server.

stdout is the JSON-RPC channel, so every record goes to stderr. Anything written to
stdout corrupts the protocol and the client sees a parse error rather than a log line.
"""

import logging
import os
import sys

LOGGER_NAME = "fred-mcp"


def configure_logging(level: str | None = None) -> None:
    """Attach a single stderr handler at the configured level. Idempotent."""
    # httpx logs every request line at INFO, and FRED takes the API key as a query
    # parameter, so at INFO the key is written to stderr on every single call. Ours
    # logs the path only. Raise httpx to WARNING before anything can emit.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel((level or os.environ.get("FRED_LOG_LEVEL") or "INFO").upper())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
