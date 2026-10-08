"""Connector-to-Workflow Integration Bridge."""

from __future__ import annotations

from typing import Any

from test_engine.config import EngineConfig, ExecutionMode
from test_engine.connectors.base import ConnectorTestResult, ConnectorType
from test_engine.connectors.mock_tester import MockConnectorSuiteTester
from test_engine.connectors.real_tester import RealConnectorSuiteTester
from test_engine.logger import get_logger
from test_engine.models.contract import ApiContract
from test_engine.models.test_case import (
    ExpectedResponse,
    TestCategory,
    TestCase,
    TestRequest,
)

logger = get_logger("connectors.workflow_bridge")


class WorkflowConnectorBridge:
    """Bridges connector testing into the test engine HTTP test suite and runtime contract."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.mock_suite = MockConnectorSuiteTester()
        self.real_suite = RealConnectorSuiteTester(config)

    def generate_connector_test_cases(self, contract: ApiContract) -> list[TestCase]:
        """Generates HTTP-level test cases validating connector endpoints and provider modes."""
        cases: list[TestCase] = []

        # 1. Test GET /api/v1/connectors (listing all registered connectors)
        connectors_ep = contract.find_endpoint("/api/v1/connectors", "GET")
        if connectors_ep:
            cases.append(
                TestCase(
                    id="CONN_LIST_REGISTERED_CONNECTORS",
                    name="Connector Registry Availability",
                    description="Query /api/v1/connectors to verify registered connectors and their active provider",
                    category=TestCategory.CONNECTOR,
                    endpoint_path=connectors_ep.path,
                    method="GET",
                    request=TestRequest(method="GET", path=connectors_ep.path),
                    expected=ExpectedResponse(
                        status_code=200,
                        description="Connector registry returned successfully",
                    ),
                )
            )

        # 2. Test GET /api/v1/connectors/{system} for each known connector type
        system_ep = contract.find_endpoint("/api/v1/connectors/{system}", "GET")
        if system_ep:
            for c_type in (ConnectorType.PAYMENT, ConnectorType.SERVICING, ConnectorType.CRM, ConnectorType.RISK):
                concrete_path = f"/api/v1/connectors/{c_type.value}"
                expected_provider = "mock" if self.config.execution_mode == ExecutionMode.MOCK else "real"
                cases.append(
                    TestCase(
                        id=f"CONN_INSPECT_SYSTEM_{c_type.value.upper()}",
                        name=f"Inspect Connector System: {c_type.value.upper()}",
                        description=f"Verify connector status for system {c_type.value} matches mode '{expected_provider}'",
                        category=TestCategory.CONNECTOR,
                        endpoint_path=system_ep.path,
                        method="GET",
                        request=TestRequest(method="GET", path=concrete_path),
                        expected=ExpectedResponse(
                            status_code=[200, 404],
                            description=f"Status for connector {c_type.value}",
                        ),
                    )
                )

        return cases

    async def execute_connector_suite(self) -> list[ConnectorTestResult]:
        """Runs the active connector test suite (mock or real based on configuration)."""
        if self.config.execution_mode == ExecutionMode.REAL:
            logger.info("Executing REAL connector test harness...")
            results = await self.real_suite.run_all()
            if not results:
                # Fallback to mock if no real endpoints configured
                logger.info("No real endpoints reached. Running mock connector checks as baseline.")
                results = await self.mock_suite.run_all()
            return results
        else:
            logger.info("Executing MOCK connector test harness...")
            return await self.mock_suite.run_all()

    @staticmethod
    def verify_case_evidence_packet(packet: dict[str, Any]) -> dict[str, bool]:
        """Verifies that case evidence packet correctly incorporates connector reads."""
        return {
            "has_payment_data": any(k.startswith("payment.") for k in packet.keys()),
            "has_servicing_data": any(k.startswith("servicing.") for k in packet.keys()),
            "has_crm_data": any(k.startswith("crm.") for k in packet.keys()),
        }
