"""
Structured logging for production trading systems.

Features:
  - JSON structured log output (machine-parseable)
  - Correlation IDs for request tracing
  - Trade event logger (every order, fill, cancel)
  - Console fallback for development
  - Log level configuration via environment
"""

from __future__ import annotations

import os
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional, Dict, Any

# Correlation ID for request tracing
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def set_correlation_id(cid: str = "") -> str:
    """Set correlation ID for the current context. Returns the ID."""
    if not cid:
        cid = uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get("")


# ------------------------------------------------------------------
# JSON Formatter
# ------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation ID if present
        cid = get_correlation_id()
        if cid:
            log_entry["correlation_id"] = cid

        # Add extras
        if hasattr(record, "trade_event"):
            log_entry["trade_event"] = record.trade_event

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, default=str)


# ------------------------------------------------------------------
# Console Formatter (human-readable)
# ------------------------------------------------------------------

class ConsoleFormatter(logging.Formatter):
    """Colored, human-readable formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        cid = get_correlation_id()
        cid_str = f" [{cid}]" if cid else ""

        msg = (
            f"{color}{record.levelname:8s}{self.RESET} "
            f"{record.name:20s}{cid_str} | "
            f"{record.getMessage()}"
        )

        if record.exc_info and record.exc_info[1]:
            msg += f"\n  Exception: {record.exc_info[1]}"

        return msg


# ------------------------------------------------------------------
# Setup function
# ------------------------------------------------------------------

def setup_logging(
    level: str = "",
    json_output: bool = False,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to LOG_LEVEL env var.
        json_output: If True, output JSON logs. Defaults to LOG_FORMAT=json env var.
    """
    if not level:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    if not json_output:
        json_output = os.environ.get("LOG_FORMAT", "console").lower() == "json"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    root.addHandler(handler)

    # Suppress noisy libraries
    for lib in ["urllib3", "ccxt", "httpx", "httpcore", "asyncio"]:
        logging.getLogger(lib).setLevel(logging.WARNING)


# ------------------------------------------------------------------
# Trade event logger
# ------------------------------------------------------------------

class TradeEventLogger:
    """
    Specialized logger for trade-related events.

    Every order submission, fill, cancel, and risk event is logged
    with structured metadata for audit and analysis.
    """

    def __init__(self):
        self.logger = logging.getLogger("vision-ai.trades")

    def _log(self, level: int, event_type: str, data: Dict[str, Any]):
        record = self.logger.makeRecord(
            name=self.logger.name,
            level=level,
            fn="",
            lno=0,
            msg=f"[{event_type}] {data.get('symbol', '')} {data.get('side', '')}",
            args=(),
            exc_info=None,
        )
        record.trade_event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self.logger.handle(record)

    def order_submitted(self, order_id: str, symbol: str, side: str,
                        order_type: str, quantity: float, price: float,
                        mode: str = "paper"):
        self._log(logging.INFO, "ORDER_SUBMITTED", {
            "order_id": order_id, "symbol": symbol, "side": side,
            "order_type": order_type, "quantity": quantity,
            "price": price, "mode": mode,
        })

    def order_filled(self, order_id: str, symbol: str, side: str,
                     filled_price: float, filled_qty: float,
                     commission: float, mode: str = "paper"):
        self._log(logging.INFO, "ORDER_FILLED", {
            "order_id": order_id, "symbol": symbol, "side": side,
            "filled_price": filled_price, "filled_qty": filled_qty,
            "commission": commission, "mode": mode,
        })

    def order_rejected(self, order_id: str, symbol: str, reason: str,
                       mode: str = "paper"):
        self._log(logging.WARNING, "ORDER_REJECTED", {
            "order_id": order_id, "symbol": symbol, "reason": reason,
            "mode": mode,
        })

    def order_cancelled(self, order_id: str, symbol: str, reason: str = ""):
        self._log(logging.INFO, "ORDER_CANCELLED", {
            "order_id": order_id, "symbol": symbol, "reason": reason,
        })

    def risk_event(self, event_type: str, message: str, severity: str):
        level = {
            "critical": logging.CRITICAL,
            "warning": logging.WARNING,
            "info": logging.INFO,
        }.get(severity, logging.INFO)

        self._log(level, f"RISK_{event_type}", {"message": message})

    def kill_switch(self, reason: str):
        self._log(logging.CRITICAL, "KILL_SWITCH_ACTIVATED", {"reason": reason})


# Singleton
trade_logger = TradeEventLogger()
