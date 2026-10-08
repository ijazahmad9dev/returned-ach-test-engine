"""Structured logging and telemetry module for Return ACH Test Engine."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

from rich.console import Console
from rich.logging import RichHandler

console = Console()

# Global execution trace collector
_ACTIVE_TRACER: TraceCollector | None = None


@dataclass
class TraceEntry:
    """Single execution trace entry."""

    timestamp: float
    level: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "metadata": self.metadata,
        }


class TraceCollector:
    """Collects logs and traces scoped to an individual test run or scenario."""

    def __init__(self, context_name: str = "") -> None:
        self.context_name = context_name
        self.entries: list[TraceEntry] = []
        self.start_time: float = time.perf_counter()
        self.end_time: float | None = None

    def record(self, level: str, message: str, **metadata: Any) -> None:
        self.entries.append(
            TraceEntry(
                timestamp=time.perf_counter(),
                level=level,
                message=message,
                metadata=metadata,
            )
        )

    def finish(self) -> float:
        self.end_time = time.perf_counter()
        return self.duration_ms

    @property
    def duration_ms(self) -> float:
        end = self.end_time if self.end_time is not None else time.perf_counter()
        return round((end - self.start_time) * 1000, 2)

    def export(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    def formatted_logs(self) -> str:
        lines: list[str] = []
        for e in self.entries:
            offset_ms = round((e.timestamp - self.start_time) * 1000, 1)
            meta_str = f" | {e.metadata}" if e.metadata else ""
            lines.append(f"[{offset_ms:>6.1f}ms] [{e.level:<5}] {e.message}{meta_str}")
        return "\n".join(lines)


class TraceLoggingHandler(logging.Handler):
    """Logging handler that forwards log records to the currently active TraceCollector."""

    def emit(self, record: logging.LogRecord) -> None:
        global _ACTIVE_TRACER
        if _ACTIVE_TRACER is not None:
            _ACTIVE_TRACER.record(
                level=record.levelname,
                message=self.format(record),
                logger=record.name,
            )


def setup_logger(level: str = "INFO", verbose: bool = False) -> logging.Logger:
    """Configures the root test engine logger with Rich formatting and trace routing."""
    root_logger = logging.getLogger("test_engine")
    root_logger.setLevel(logging.DEBUG if verbose else level.upper())

    # Prevent duplicate handlers on re-initialization
    if not root_logger.handlers:
        rich_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=verbose,
            markup=True,
            rich_tracebacks=True,
        )
        rich_handler.setLevel(logging.DEBUG if verbose else level.upper())
        formatter = logging.Formatter("%(message)s")
        rich_handler.setFormatter(formatter)
        root_logger.addHandler(rich_handler)

        trace_handler = TraceLoggingHandler()
        trace_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(trace_handler)

    return root_logger


def get_logger(name: str = "test_engine") -> logging.Logger:
    """Retrieve a named child logger."""
    return logging.getLogger(f"test_engine.{name}")


@contextmanager
def trace_context(context_name: str = "") -> Generator[TraceCollector, None, None]:
    """Context manager that scopes log capture to a specific test or scenario."""
    global _ACTIVE_TRACER
    previous = _ACTIVE_TRACER
    collector = TraceCollector(context_name=context_name)
    _ACTIVE_TRACER = collector
    try:
        yield collector
    finally:
        collector.finish()
        _ACTIVE_TRACER = previous
