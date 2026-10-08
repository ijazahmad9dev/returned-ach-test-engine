"""Base abstraction and protocols for connector testing (mock and real)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ConnectorType(str, Enum):
    """Supported external upstream system connector types."""

    PAYMENT = "payment"
    CRM = "crm"
    SERVICING = "servicing"
    RISK = "risk"


class ConnectorHealth(str, Enum):
    """Health status of an external connector."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


@dataclass
class ConnectorTestResult:
    """Outcome of testing a connector operation."""

    connector_name: str
    connector_type: ConnectorType
    mode: Literal["mock", "real"]
    operation: str
    status: Literal["PASS", "FAIL", "SKIPPED"]
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "PASS"


class BaseConnectorTester(ABC):
    """Abstract base class for testing connector capabilities."""

    def __init__(self, connector_type: ConnectorType, mode: Literal["mock", "real"] = "mock") -> None:
        self.connector_type = connector_type
        self.mode = mode

    @abstractmethod
    async def check_health(self) -> ConnectorHealth:
        """Pings upstream service to check health status."""
        ...

    @abstractmethod
    async def test_read_operations(self) -> list[ConnectorTestResult]:
        """Tests read operations (e.g. get_return_event, get_account, get_contact)."""
        ...

    @abstractmethod
    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        """Tests handling of upstream timeouts, missing resources, and invalid tokens."""
        ...
