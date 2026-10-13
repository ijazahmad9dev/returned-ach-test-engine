"""Tests validating Phase 1 Handoff Compliance:
- Read-only by default (--allow-writes safety)
- Exact status codes (no false passes on 404/409)
- Fresh dynamic data each run (unique references and real dates)
- CORS origin restriction & target host whitelist protection
"""

from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient

from test_engine.config import EngineConfig
from test_engine.models.contract import EndpointContract
from test_engine.models.result import TestStatus
from test_engine.models.test_case import ExpectedResponse, TestCategory, TestCase, TestRequest
from test_engine.execution.client import ExecutionResponse
from test_engine.scenarios.ach_domain_generator import AchDomainScenarioGenerator
from test_engine.scenarios.schema_generator import SchemaScenarioGenerator
from test_engine.server import create_app
from test_engine.validation.validator import ResponseValidator


def test_read_only_by_default_prevents_connector_mutation():
    """Verify engine defaults to read-only and skips mutating endpoints unless allow_writes=True."""
    config = EngineConfig()
    assert config.allow_writes is False

    schema_gen_readonly = SchemaScenarioGenerator(allow_writes=False)
    connector_endpoint = EndpointContract(
        path="/api/v1/connectors/{system}",
        method="PUT",
        request_schema={"type": "object", "properties": {"provider": {"type": "string"}}},
    )

    # In read-only mode, mutating connector endpoint must be skipped
    cases_readonly = schema_gen_readonly.generate_scenarios(connector_endpoint)
    assert len(cases_readonly) == 0

    # In allow_writes mode, mutating connector endpoint is permitted
    schema_gen_writes = SchemaScenarioGenerator(allow_writes=True)
    cases_writes = schema_gen_writes.generate_scenarios(connector_endpoint)
    assert len(cases_writes) > 0


def test_exact_status_code_rejects_false_passes():
    """Verify validator requires exact status code and fails 404/409 responses."""
    validator = ResponseValidator()

    test_case = TestCase(
        id="TC_STRICT_201",
        name="Strict 201 Requirement",
        description="Must fail if status is 404 or 409",
        category=TestCategory.ACH_DOMAIN,
        endpoint_path="/api/v1/triggers/returned-ach",
        method="POST",
        request=TestRequest(path="/api/v1/triggers/returned-ach"),
        expected=ExpectedResponse(
            status_code=201,
            expected_keys=["case_id", "created"],
        ),
    )

    # 404 response must FAIL (no more false passes)
    resp_404 = ExecutionResponse(
        status_code=404,
        json_body={"error": {"code": "NOT_FOUND"}},
        latency_ms=10.0,
    )
    status, failures, _, diff = validator.validate(test_case, resp_404)
    assert status == TestStatus.FAIL
    assert any("HTTP status code mismatch" in f for f in failures)
    assert "404" in str(diff)

    # 409 response must FAIL
    resp_409 = ExecutionResponse(
        status_code=409,
        json_body={"error": {"code": "CONFLICT"}},
        latency_ms=10.0,
    )
    status, failures, _, _ = validator.validate(test_case, resp_409)
    assert status == TestStatus.FAIL

    # Exact 201 must PASS
    resp_201 = ExecutionResponse(
        status_code=201,
        json_body={"case_id": "test_id", "created": True},
        latency_ms=10.0,
    )
    status, failures, _, _ = validator.validate(test_case, resp_201)
    assert status == TestStatus.PASS


def test_fresh_test_data_and_today_dates_each_run():
    """Verify dynamic references and real-time dates are generated on every run."""
    gen = AchDomainScenarioGenerator()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    payload1 = gen._base_ach_payload(reason_code="R01")
    payload2 = gen._base_ach_payload(reason_code="R01")

    # Dates must match today
    assert payload1["return_settlement_date"] == today_str
    assert payload2["return_settlement_date"] == today_str

    # Trace numbers must be unique across runs to avoid duplicate replays
    assert payload1["original_trace_number"] != payload2["original_trace_number"]
    assert payload1["source_event_id"] != payload2["source_event_id"]

    # Entities must use recognized test accounts (not unknown sample IDs)
    assert payload1["account_ref"] == "ACC-0001"
    assert payload1["customer_ref"] == "CUS-0001"


def test_server_blocks_unauthorized_target_hosts():
    """Verify web UI blocks arbitrary external website target URLs (SSRF protection)."""
    app = create_app()
    client = TestClient(app)

    # Discover against malicious external host must be rejected with 400
    res = client.post("/api/discover", json={"target_url": "http://malicious-external-site.com"})
    assert res.status_code == 400
    assert "not in allowed target hosts" in res.json()["detail"]

    # Run against malicious host must be rejected with 400
    res_run = client.post("/api/run", json={"target_url": "https://attacker-controlled.io/api"})
    assert res_run.status_code == 400
    assert "not in allowed target hosts" in res_run.json()["detail"]
