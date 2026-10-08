"""Tests for test_engine.logger."""

import logging
import time

from test_engine.logger import get_logger, setup_logger, trace_context


def test_logger_setup() -> None:
    logger = setup_logger(level="DEBUG", verbose=True)
    assert logger.name == "test_engine"
    assert logger.level == logging.DEBUG

    child = get_logger("test_module")
    assert child.name == "test_engine.test_module"


def test_trace_context_capture() -> None:
    logger = get_logger("scenario")

    with trace_context("test_scenario_1") as tracer:
        assert tracer.context_name == "test_scenario_1"
        tracer.record("INFO", "Starting test", step=1)
        logger.info("Executing mock request")
        time.sleep(0.01)

    assert tracer.duration_ms >= 10.0
    assert len(tracer.entries) >= 2
    assert tracer.entries[0].message == "Starting test"
    assert tracer.entries[0].metadata == {"step": 1}

    formatted = tracer.formatted_logs()
    assert "Starting test" in formatted
    assert "Executing mock request" in formatted

    exported = tracer.export()
    assert isinstance(exported, list)
    assert len(exported) >= 2
