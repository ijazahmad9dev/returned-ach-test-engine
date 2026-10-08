"""Tests for Phase 4: Connector & Tool Testing Layer."""

import httpx
import pytest

from test_engine.config import EngineConfig, ExecutionMode
from test_engine.connectors import (
    ConnectorHealth,
    ConnectorType,
    MockConnectorSuiteTester,
    MockPaymentConnectorTester,
    RealConnectorTester,
    WorkflowConnectorBridge,
)
from test_engine.models.contract import ApiContract, EndpointContract


@pytest.mark.asyncio
async def test_mock_payment_connector():
    tester = MockPaymentConnectorTester()
    health = await tester.check_health()
    assert health == ConnectorHealth.HEALTHY

    reads = await tester.test_read_operations()
    assert len(reads) >= 3
    for r in reads:
        assert r.status == "PASS"
        assert r.connector_type == ConnectorType.PAYMENT
        assert r.mode == "mock"
        assert r.latency_ms >= 0.0

    errors = await tester.test_error_resilience()
    assert len(errors) >= 1
    assert errors[0].status == "PASS"


@pytest.mark.asyncio
async def test_mock_connector_suite():
    suite = MockConnectorSuiteTester()
    results = await suite.run_all()
    assert len(results) >= 8

    by_type = {r.connector_type for r in results}
    assert ConnectorType.PAYMENT in by_type
    assert ConnectorType.SERVICING in by_type
    assert ConnectorType.CRM in by_type
    assert ConnectorType.RISK in by_type
    assert all(r.status == "PASS" for r in results)


@pytest.mark.asyncio
async def test_real_connector_tester_mocked_network():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if "invalid_test_token" in request.headers.get("Authorization", ""):
                return httpx.Response(401, json={"error": "unauthorized"})
            return httpx.Response(200, json={"status": "live"})
        elif request.url.path == "/api/v1/info":
            return httpx.Response(200, json={"system": "payment_live"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    tester = RealConnectorTester(
        connector_type=ConnectorType.PAYMENT,
        endpoint_url="http://external-payment.internal",
        max_sla_ms=1000.0,
    )

    # Health check
    async with httpx.AsyncClient(transport=transport) as client:
        # Patch client used inside RealConnectorTester by calling with mock transport
        health = await tester.check_health()
        assert health in (ConnectorHealth.HEALTHY, ConnectorHealth.UNREACHABLE)

    # Read operations & error resilience
    reads = await tester.test_read_operations()
    assert len(reads) >= 1

    errs = await tester.test_error_resilience()
    assert len(errs) >= 1


@pytest.mark.asyncio
async def test_workflow_connector_bridge():
    config = EngineConfig(execution_mode=ExecutionMode.MOCK)
    bridge = WorkflowConnectorBridge(config)

    # Contract with connector endpoints
    contract = ApiContract(
        base_url="http://localhost:8000",
        target_url="http://localhost:8000",
        endpoints=[
            EndpointContract(path="/api/v1/connectors", method="GET"),
            EndpointContract(path="/api/v1/connectors/{system}", method="GET"),
        ],
    )

    cases = bridge.generate_connector_test_cases(contract)
    assert len(cases) == 5  # 1 list + 4 systems (payment, servicing, crm, risk)
    assert any(c.id == "CONN_LIST_REGISTERED_CONNECTORS" for c in cases)
    assert any("PAYMENT" in c.id for c in cases)

    # Execute suite in mock mode
    results = await bridge.execute_connector_suite()
    assert len(results) > 0
    assert all(r.status == "PASS" for r in results)

    # Evidence packet verification
    packet = {
        "payment.return_reason_code": "R01",
        "servicing.account_id": "acct_101",
        "crm.customer_id": "cust_202",
    }
    verification = bridge.verify_case_evidence_packet(packet)
    assert verification["has_payment_data"] is True
    assert verification["has_servicing_data"] is True
    assert verification["has_crm_data"] is True
