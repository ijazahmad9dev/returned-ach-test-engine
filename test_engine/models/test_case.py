"""Data models for test cases, requests, expected responses, and categories."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class TestCategory(str, Enum):
    """Classification of test scenario."""
    __test__ = False

    HEALTH = "health"
    SCHEMA = "schema"
    ACH_DOMAIN = "ach_domain"
    ERROR_HANDLING = "error_handling"
    SECURITY = "security"
    LIFECYCLE = "lifecycle"
    CONNECTOR = "connector"


class TestRequest(BaseModel):
    """Specification of the HTTP request to be executed."""
    __test__ = False

    method: str = "POST"
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any | None = None
    raw_body: str | None = None  # Used for testing malformed JSON payloads

    @property
    def display_body(self) -> Any:
        return self.raw_body if self.raw_body is not None else self.json_body


class ExpectedResponse(BaseModel):
    """Expected criteria for response validation."""
    __test__ = False

    status_code: int | list[int] = 200
    expected_error_code: str | None = None
    expected_error_field: str | None = None
    expected_keys: list[str] = Field(default_factory=list)
    schema_definition: dict[str, Any] | None = None
    max_latency_ms: float | None = 5000.0
    description: str = ""


class TestCase(BaseModel):
    """A single executable test scenario."""
    __test__ = False

    id: str
    name: str
    description: str
    category: TestCategory
    endpoint_path: str
    method: str = "POST"
    request: TestRequest
    expected: ExpectedResponse

    # Lifecycle & dependency metadata for stateful multi-step testing
    is_stateful: bool = False
    step_number: int | None = None
    depends_on: str | None = None
    # Maps variable name in scenario context to response JSON path (e.g. {"case_id": "case_id"})
    context_extractors: dict[str, str] = Field(default_factory=dict)
