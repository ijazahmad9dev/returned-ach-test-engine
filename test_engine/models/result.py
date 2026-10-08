"""Data models for test execution results, validation outcomes, and diffs."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from test_engine.models.test_case import TestCategory


class TestStatus(str, Enum):
    __test__ = False
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class ValidationOutcome(BaseModel):
    """Outcome of validating a single assertion or criterion."""
    __test__ = False

    rule_name: str
    passed: bool
    expected: Any
    actual: Any
    message: str = ""


class TestExecutionResult(BaseModel):
    """Comprehensive record of executing a single test scenario."""
    __test__ = False

    test_id: str
    name: str
    description: str
    category: TestCategory
    status: TestStatus
    http_status_code: int | None = None
    execution_time_ms: float = 0.0

    # Input and Output tracking
    request_method: str
    request_url: str
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_body: Any | None = None

    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: Any | None = None
    response_raw_text: str = ""

    # Expected vs Actual evaluation
    expected_status_code: Any
    expected_error_code: str | None = None
    validation_failures: list[str] = Field(default_factory=list)
    validation_details: list[ValidationOutcome] = Field(default_factory=list)
    diff_summary: str | None = None
    error_info: str | None = None

    # Telemetry and Execution Logs
    logs: str = ""
    timestamp: float = Field(default_factory=time.time)

    @property
    def is_passed(self) -> bool:
        return self.status == TestStatus.PASS
