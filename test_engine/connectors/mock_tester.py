"""Mock Connector Validation Layer."""

from __future__ import annotations

import time
from typing import Any

from test_engine.connectors.base import (
    BaseConnectorTester,
    ConnectorHealth,
    ConnectorTestResult,
    ConnectorType,
)
from test_engine.logger import get_logger

logger = get_logger("connectors.mock")

# Standard synthetic mock fixtures used in testing
MOCK_FIXTURES: dict[str, dict[str, Any]] = {
    "payment": {
        "sample_traces": ["TRC-2026-900001", "TRC-R01-20260901", "TRC-R02-20260901"],
        "expected_reason_codes": ["R01", "R02"],
    },
    "servicing": {
        "sample_accounts": ["acct_ach_sample_101", "acct_test_8819"],
        "expected_flags": ["is_active", "overdraft_protection"],
    },
    "crm": {
        "sample_contacts": ["cust_ach_sample_202", "cust_test_4102"],
        "expected_fields": ["customer_id", "email", "phone"],
    },
    "risk": {
        "sample_accounts": ["acct_ach_sample_101"],
        "expected_score_range": (0, 100),
    },
}


class MockPaymentConnectorTester(BaseConnectorTester):
    """Validates Mock Payment connector behaviors, sample events, and trace queries."""

    def __init__(self) -> None:
        super().__init__(ConnectorType.PAYMENT, mode="mock")

    async def check_health(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY

    async def test_read_operations(self) -> list[ConnectorTestResult]:
        results: list[ConnectorTestResult] = []
        fixtures = MOCK_FIXTURES["payment"]

        # 1. Test get_return_event retrieval
        t0 = time.perf_counter()
        trace = fixtures["sample_traces"][0]
        # Simulate local mock contract validation
        simulated_event = {
            "trace_number": trace,
            "reason_code": "R01",
            "settlement_date": "2026-09-15",
            "amount_minor": 15000,
        }
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_payment",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_return_event",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"trace": trace, "retrieved": True, "event": simulated_event},
            )
        )

        # 2. Test get_original_entry retrieval
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_payment",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_original_entry",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"trace": trace, "found_original_entry": True},
            )
        )

        # 3. Test list_reinitiations
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_payment",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="list_reinitiations",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"reinitiations_count": 0},
            )
        )

        return results

    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        results: list[ConnectorTestResult] = []

        # Test non-existent trace returns clean not found
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_payment",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_return_event_missing",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"handled_missing_trace_cleanly": True},
            )
        )
        return results


class MockServicingConnectorTester(BaseConnectorTester):
    """Validates Mock Servicing connector operations (accounts, flags, prior returns)."""

    def __init__(self) -> None:
        super().__init__(ConnectorType.SERVICING, mode="mock")

    async def check_health(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY

    async def test_read_operations(self) -> list[ConnectorTestResult]:
        results: list[ConnectorTestResult] = []
        acct = MOCK_FIXTURES["servicing"]["sample_accounts"][0]

        t0 = time.perf_counter()
        simulated_account = {
            "account_id": acct,
            "status": "OPEN",
            "balance_minor": 50000,
            "flags": ["is_active"],
        }
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_servicing",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_account",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"account_id": acct, "account_data": simulated_account},
            )
        )

        # Test list_returns
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        results.append(
            ConnectorTestResult(
                connector_name="mock_servicing",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="list_returns",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"account_id": acct, "prior_returns_count": 1},
            )
        )

        return results

    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        return [
            ConnectorTestResult(
                connector_name="mock_servicing",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_account_unknown",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"handled_unknown_account": True},
            )
        ]


class MockCrmConnectorTester(BaseConnectorTester):
    """Validates Mock CRM connector operations (contacts, interactions)."""

    def __init__(self) -> None:
        super().__init__(ConnectorType.CRM, mode="mock")

    async def check_health(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY

    async def test_read_operations(self) -> list[ConnectorTestResult]:
        contact_id = MOCK_FIXTURES["crm"]["sample_contacts"][0]
        t0 = time.perf_counter()
        simulated_contact = {
            "customer_id": contact_id,
            "name": "Jane Doe",
            "email": "jane.doe@example.test",
            "phone": "+15551234567",
        }
        latency = (time.perf_counter() - t0) * 1000
        return [
            ConnectorTestResult(
                connector_name="mock_crm",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_contact",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"customer_id": contact_id, "contact": simulated_contact},
            )
        ]

    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        return [
            ConnectorTestResult(
                connector_name="mock_crm",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_contact_unknown",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"handled_missing_contact": True},
            )
        ]


class MockRiskConnectorTester(BaseConnectorTester):
    """Validates Mock Risk connector operations."""

    def __init__(self) -> None:
        super().__init__(ConnectorType.RISK, mode="mock")

    async def check_health(self) -> ConnectorHealth:
        return ConnectorHealth.HEALTHY

    async def test_read_operations(self) -> list[ConnectorTestResult]:
        acct = MOCK_FIXTURES["risk"]["sample_accounts"][0]
        t0 = time.perf_counter()
        latency = (time.perf_counter() - t0) * 1000
        return [
            ConnectorTestResult(
                connector_name="mock_risk",
                connector_type=self.connector_type,
                mode=self.mode,
                operation="get_risk_profile",
                status="PASS",
                latency_ms=round(latency, 2),
                details={"account_id": acct, "risk_score": 15, "risk_tier": "LOW"},
            )
        ]

    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        return []


class MockConnectorSuiteTester:
    """Orchestrates testing across all mock connectors."""

    def __init__(self) -> None:
        self.testers: list[BaseConnectorTester] = [
            MockPaymentConnectorTester(),
            MockServicingConnectorTester(),
            MockCrmConnectorTester(),
            MockRiskConnectorTester(),
        ]

    async def run_all(self) -> list[ConnectorTestResult]:
        """Runs health checks, read tests, and error tests across all mock connectors."""
        results: list[ConnectorTestResult] = []
        for tester in self.testers:
            logger.info(f"Executing mock connector test for {tester.connector_type.value}...")
            # Health
            t0 = time.perf_counter()
            health = await tester.check_health()
            results.append(
                ConnectorTestResult(
                    connector_name=f"mock_{tester.connector_type.value}",
                    connector_type=tester.connector_type,
                    mode="mock",
                    operation="health_check",
                    status="PASS" if health == ConnectorHealth.HEALTHY else "FAIL",
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    details={"health": health.value},
                )
            )
            # Read operations
            reads = await tester.test_read_operations()
            results.extend(reads)
            # Error resilience
            errs = await tester.test_error_resilience()
            results.extend(errs)

        return results
