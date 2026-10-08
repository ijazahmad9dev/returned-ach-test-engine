"""Tests for Phase 5: Test Execution & Validation Engine."""

import httpx
import pytest

from test_engine.config import EngineConfig
from test_engine.execution.client import ExecutionHttpClient, ExecutionResponse
from test_engine.execution.runner import TestRunner
from test_engine.models.result import TestStatus
from test_engine.models.test_case import (
    ExpectedResponse,
    TestCategory,
    TestCase,
    TestRequest,
)
from test_engine.validation.diff_analyzer import DiffAnalyzer
from test_engine.validation.validator import ResponseValidator


@pytest.mark.asyncio
async def test_execution_http_client_mock():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-User-Id") == "usr_test_01"
        if request.url.path == "/api/v1/test":
            return httpx.Response(200, json={"status": "ok", "echo": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as raw_client:
        config = EngineConfig(auth_user_id="usr_test_01")
        client = ExecutionHttpClient(config, client=raw_client)

        resp = await client.execute("GET", "/api/v1/test")
        assert resp.status_code == 200
        assert resp.json_body == {"status": "ok", "echo": True}
        assert resp.latency_ms >= 0.0


def test_validator_success_and_failure():
    validator = ResponseValidator()

    test_case = TestCase(
        id="TC_01",
        name="Test Trigger",
        description="Verify 201 response with case_id",
        category=TestCategory.ACH_DOMAIN,
        endpoint_path="/api/v1/triggers/returned-ach",
        method="POST",
        request=TestRequest(path="/api/v1/triggers/returned-ach"),
        expected=ExpectedResponse(
            status_code=[200, 201],
            expected_keys=["case_id", "created"],
            max_latency_ms=1000.0,
        ),
    )

    # 1. Matching response
    success_resp = ExecutionResponse(
        status_code=201,
        json_body={"case_id": "case_123", "created": True},
        latency_ms=45.2,
    )
    status, failures, outcomes, diff = validator.validate(test_case, success_resp)
    assert status == TestStatus.PASS
    assert len(failures) == 0
    assert diff is None

    # 2. Failing status code
    fail_resp = ExecutionResponse(
        status_code=500,
        json_body={"error": {"code": "INTERNAL_ERROR"}},
        latency_ms=50.0,
    )
    status, failures, outcomes, diff = validator.validate(test_case, fail_resp)
    assert status == TestStatus.FAIL
    assert len(failures) > 0
    assert "HTTP Status Mismatch" in diff


def test_validator_error_envelope():
    validator = ResponseValidator()

    test_case = TestCase(
        id="TC_ERR_01",
        name="Missing Trace",
        description="Expect 422 error on original_trace_number",
        category=TestCategory.SCHEMA,
        endpoint_path="/api/v1/triggers/returned-ach",
        method="POST",
        request=TestRequest(path="/api/v1/triggers/returned-ach"),
        expected=ExpectedResponse(
            status_code=422,
            expected_error_code="INVALID_INPUT",
            expected_error_field="original_trace_number",
        ),
    )

    # Response with proper ErrorEnvelope
    err_resp = ExecutionResponse(
        status_code=422,
        json_body={
            "error": {
                "code": "INVALID_INPUT",
                "message": "Validation failed",
                "fields": [
                    {"path": "body.original_trace_number", "message": "Field required"}
                ],
            }
        },
        latency_ms=15.0,
    )
    status, failures, outcomes, diff = validator.validate(test_case, err_resp)
    assert status == TestStatus.PASS
    assert len(failures) == 0


def test_diff_analyzer():
    diff = DiffAnalyzer.format_diff(
        expected_status=200,
        actual_status=422,
        expected_error_code="NOT_FOUND",
        actual_error_code="INVALID_INPUT",
        expected_field="tenant_id",
        actual_fields=["amount_minor"],
        missing_keys=["case_id"],
    )
    assert "HTTP Status Mismatch" in diff
    assert "Error Code Mismatch" in diff
    assert "Missing Expected Error Field" in diff
    assert "Missing Expected Response Keys" in diff


@pytest.mark.asyncio
async def test_runner_concurrency_and_lifecycle():
    # Mock transport handling multi-step lifecycle
    created_case_id = "case_generated_99901"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/triggers/returned-ach":
            return httpx.Response(201, json={"case_id": created_case_id, "created": True})
        elif request.url.path == f"/api/v1/cases/{created_case_id}":
            return httpx.Response(200, json={"case_id": created_case_id, "state": "opened"})
        elif request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as raw_client:
        config = EngineConfig(max_concurrency=2)
        http_client = ExecutionHttpClient(config, client=raw_client)
        runner = TestRunner(config, http_client=http_client)

        # 1 independent test
        health_case = TestCase(
            id="TC_HEALTH",
            name="Health check",
            description="Check health",
            category=TestCategory.HEALTH,
            endpoint_path="/api/v1/health",
            method="GET",
            request=TestRequest(path="/api/v1/health"),
            expected=ExpectedResponse(status_code=200, expected_keys=["status"]),
        )

        # 2 sequential lifecycle tests
        step1 = TestCase(
            id="TC_STEP1",
            name="Trigger step",
            description="Trigger workflow",
            category=TestCategory.LIFECYCLE,
            endpoint_path="/api/v1/triggers/returned-ach",
            method="POST",
            request=TestRequest(path="/api/v1/triggers/returned-ach", json_body={}),
            expected=ExpectedResponse(status_code=201, expected_keys=["case_id"]),
            is_stateful=True,
            step_number=1,
            context_extractors={"case_id": "case_id"},
        )
        step2 = TestCase(
            id="TC_STEP2",
            name="Inspect created case",
            description="Inspect case using dynamic case_id",
            category=TestCategory.LIFECYCLE,
            endpoint_path="/api/v1/cases/{case_id}",
            method="GET",
            request=TestRequest(path="/api/v1/cases/{case_id}"),
            expected=ExpectedResponse(status_code=200, expected_keys=["state"]),
            is_stateful=True,
            step_number=2,
            depends_on="TC_STEP1",
        )

        results = await runner.run_all([health_case, step1, step2])
        assert len(results) == 3
        assert all(r.status == TestStatus.PASS for r in results)

        # Verify step 2 had {case_id} substituted with created_case_id
        step2_res = [r for r in results if r.test_id == "TC_STEP2"][0]
        assert f"/api/v1/cases/{created_case_id}" in step2_res.request_url
        assert step2_res.response_body["state"] == "opened"
        assert len(step2_res.logs) > 0
