"""End-to-End integration tests for Return ACH Test Engine against simulated backend."""

import json
import tempfile
from pathlib import Path

import httpx
import pytest

from test_engine.config import EngineConfig, ExecutionMode
from test_engine.models.report import FullTestReport
from test_engine.models.result import TestStatus
from test_engine.orchestration.graph import run_test_workflow
from test_engine.reporting.exporters import ReportExporterManager
from tests.test_discovery import SAMPLE_OPENAPI_SPEC


class MockReturnAchBackend:
    """Simulates the Return ACH FastAPI backend for End-to-End testing."""

    def __init__(self) -> None:
        self.received_triggers: dict[str, str] = {}  # dedupe_key -> case_id
        self.case_counter = 100

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        # 1. Health
        if path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok", "version": "1.0.0"})

        # 2. OpenAPI specification
        if path == "/openapi.json":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=SAMPLE_OPENAPI_SPEC,
            )

        # 3. Triggers endpoint
        if path == "/api/v1/triggers/returned-ach":
            if request.method != "POST":
                return httpx.Response(405, json={"error": {"code": "METHOD_NOT_ALLOWED"}})

            try:
                body = json.loads(request.content)
            except Exception:
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "Malformed JSON",
                            "fields": [{"path": "body", "message": "JSON decode error"}],
                        }
                    },
                )

            # Check required fields
            required_fields = ["tenant_id", "original_trace_number", "return_reason_code", "amount_minor", "currency"]
            for rf in required_fields:
                if rf not in body:
                    return httpx.Response(
                        422,
                        json={
                            "error": {
                                "code": "INVALID_INPUT",
                                "message": f"Missing required field {rf}",
                                "fields": [{"path": f"body.{rf}", "message": "field required"}],
                            }
                        },
                    )

            # Check extra property in strict mode
            if "__unexpected_strict_field__" in body:
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "Extra fields not permitted",
                            "fields": [{"path": "body.__unexpected_strict_field__", "message": "extra forbidden"}],
                        }
                    },
                )

            # Validate types and bounds
            if not isinstance(body.get("amount_minor"), int) or body.get("amount_minor") < 0:
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "amount_minor must be >= 0 integer",
                            "fields": [{"path": "body.amount_minor", "message": "greater than or equal to 0"}],
                        }
                    },
                )

            # Validate reason code pattern ^R\d{2}$
            reason = str(body.get("return_reason_code", ""))
            if not (len(reason) == 3 and reason.upper().startswith("R") and reason[1:].isdigit()):
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "invalid reason code",
                            "fields": [{"path": "body.return_reason_code", "message": "pattern mismatch"}],
                        }
                    },
                )

            # Validate trace length 6-64
            trace = str(body.get("original_trace_number", ""))
            if len(trace) < 6 or "@" in trace or "#" in trace or "!" in trace:
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "invalid trace number",
                            "fields": [{"path": "body.original_trace_number", "message": "invalid length/pattern"}],
                        }
                    },
                )

            # Validate settlement date year >= 2000
            settlement_date = str(body.get("return_settlement_date", "2026-09-15"))
            if settlement_date < "2000":
                return httpx.Response(
                    422,
                    json={
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "date implausibly old",
                            "fields": [{"path": "body.return_settlement_date", "message": "year must be >= 2000"}],
                        }
                    },
                )

            # Deduplication key check: (trace, reason, date)
            dedupe_key = f"{trace}:{reason}:{settlement_date}"
            if dedupe_key in self.received_triggers:
                return httpx.Response(
                    200,
                    json={
                        "case_id": self.received_triggers[dedupe_key],
                        "created": False,
                        "reopened": False,
                    },
                )

            self.case_counter += 1
            new_case_id = f"case_ach_{self.case_counter}"
            self.received_triggers[dedupe_key] = new_case_id
            return httpx.Response(
                201,
                json={"case_id": new_case_id, "created": True, "reopened": False},
            )

        # 4. Cases endpoint
        if path.startswith("/api/v1/cases/"):
            case_id = path.split("/")[-1]
            if "non_existent" in case_id:
                return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "Case not found"}})
            return httpx.Response(200, json={"case_id": case_id, "state": "opened"})

        # 5. Connectors endpoint
        if path == "/api/v1/connectors":
            return httpx.Response(
                200,
                json={
                    "connectors": [
                        {"system": "payment", "provider": "mock"},
                        {"system": "servicing", "provider": "mock"},
                        {"system": "crm", "provider": "mock"},
                    ]
                },
            )

        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "Route not found"}})


@pytest.mark.asyncio
async def test_e2e_base_url_run(monkeypatch):
    backend = MockReturnAchBackend()
    transport = httpx.MockTransport(backend.handle)

    # Patch httpx.AsyncClient to use our in-process MockReturnAchBackend transport
    orig_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir) / "test_reports"

        config = EngineConfig(
            target_url="http://localhost:8000",
            execution_mode=ExecutionMode.MOCK,
            suites=["schema", "ach_domain", "security", "health"],
            output_dir=out_dir,
            max_concurrency=4,
            report_formats=["json", "markdown", "html"],
        )

        final_state = await run_test_workflow(config)

        assert final_state["workflow_status"] == "completed"
        assert final_state["is_reachable"] is True
        assert final_state["health_ok"] is True

        summary = final_state["report_summary"]
        assert summary["total_tests"] > 20
        assert summary["passed"] > 15
        assert summary["total_duration_ms"] > 0

        # Export and verify disk artifacts
        raw_results = final_state.get("execution_results", [])
        from test_engine.models.result import TestExecutionResult

        results = [TestExecutionResult.model_validate(r) for r in raw_results]
        report = FullTestReport.from_results(
            target_url=config.target_url,
            execution_mode=config.execution_mode.value,
            results=results,
            is_reachable=True,
            health_ok=True,
        )

        exported = ReportExporterManager.export_all(
            report=report,
            output_dir=out_dir,
            formats=config.report_formats,
        )

        assert (out_dir / "report.json").exists()
        assert (out_dir / "report.md").exists()
        assert (out_dir / "report.html").exists()

        # Check content in generated artifacts
        md_content = (out_dir / "report.md").read_text(encoding="utf-8")
        assert "Return ACH Test Engine Report" in md_content
        assert "ACH_REASON_CODE_R01" in md_content

        html_content = (out_dir / "report.html").read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html_content
        assert "Return ACH Test Engine Report" in html_content


@pytest.mark.asyncio
async def test_e2e_single_endpoint_mode(monkeypatch):
    backend = MockReturnAchBackend()
    transport = httpx.MockTransport(backend.handle)

    orig_async_client = httpx.AsyncClient

    def mock_async_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)

    # Single endpoint target
    config = EngineConfig(
        target_url="http://localhost:8000/api/v1/triggers/returned-ach",
        execution_mode=ExecutionMode.MOCK,
        suites=["schema"],
    )

    final_state = await run_test_workflow(config)
    assert final_state["workflow_status"] == "completed"
    assert final_state["is_reachable"] is True

    # Verify only the single targeted endpoint was tested
    contract_data = final_state["contract_data"]
    assert len(contract_data["endpoints"]) == 1
    assert contract_data["endpoints"][0]["path"] == "/api/v1/triggers/returned-ach"
