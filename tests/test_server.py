"""Tests for the Frontend Dashboard server and API routes."""

import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from test_engine.server import create_app
from tests.test_discovery import SAMPLE_OPENAPI_SPEC


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_server_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "engine_version" in data


def test_server_serve_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Return ACH Test Engine" in response.text
    assert "text/html" in response.headers["content-type"]


def test_server_static_assets(client):
    css_res = client.get("/static/style.css")
    assert css_res.status_code == 200
    assert "--bg-primary" in css_res.text

    js_res = client.get("/static/app.js")
    assert js_res.status_code == 200
    assert "appState" in js_res.text


def test_server_discover_endpoint(client, monkeypatch):
    # Mock OpenApiFetcher inside server
    from test_engine.discovery.openapi_fetcher import OpenApiFetcher
    from test_engine.discovery.resolver import TargetResolution, TargetResolver

    async def mock_resolve(self, client=None):
        return TargetResolution(
            target_url="http://mockbackend:8000",
            base_url="http://mockbackend:8000",
            is_single_endpoint=False,
            endpoint_path=None,
            is_reachable=True,
            health_ok=True,
            openapi_url="http://mockbackend:8000/openapi.json",
        )

    async def mock_fetch(self, url, client=None):
        return SAMPLE_OPENAPI_SPEC

    monkeypatch.setattr(TargetResolver, "resolve", mock_resolve)
    monkeypatch.setattr(OpenApiFetcher, "fetch", mock_fetch)

    response = client.post("/api/discover", json={"target_url": "http://mockbackend:8000"})
    assert response.status_code == 200
    data = response.json()
    assert data["is_reachable"] is True
    assert data["health_ok"] is True
    assert "contract" in data
    assert len(data["contract"]["endpoints"]) == 3


def test_server_list_reports(client):
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create dummy report file in directory
        p = Path(tmp_dir) / "report.json"
        p.write_text('{"summary": {"target_url": "http://test", "total_tests": 5, "passed": 5}}')

        response = client.get(f"/api/reports?output_dir={tmp_dir}")
        assert response.status_code == 200
        reports = response.json()
        assert len(reports) == 1
        assert reports[0]["filename"] == "report.json"
        assert reports[0]["md_filename"] == "report.md"
        assert reports[0]["total_tests"] == 5


def test_server_download_json_report(client):
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir) / "report.json"
        p.write_text('{"summary": {"target_url": "http://test", "total_tests": 10, "passed": 10}}')

        # 1. Normal view
        res = client.get(f"/api/reports/report.json?output_dir={tmp_dir}")
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["total_tests"] == 10

        # 2. Download mode
        res_dl = client.get(f"/api/reports/report.json?output_dir={tmp_dir}&download=true")
        assert res_dl.status_code == 200
        assert "attachment" in res_dl.headers.get("content-disposition", "")
        assert 'filename="report.json"' in res_dl.headers.get("content-disposition", "")
        assert "application/json" in res_dl.headers.get("content-type", "")


def test_server_download_markdown_report(client):
    with tempfile.TemporaryDirectory() as tmp_dir:
        p = Path(tmp_dir) / "report.md"
        p.write_text("# Return ACH Test Engine Report\nTotal Tests: 10")

        # 1. Normal view
        res = client.get(f"/api/reports/report.md?output_dir={tmp_dir}")
        assert res.status_code == 200
        assert "text/markdown" in res.headers.get("content-type", "")
        assert "Return ACH Test Engine Report" in res.text

        # 2. Download mode
        res_dl = client.get(f"/api/reports/report.md?output_dir={tmp_dir}&download=true")
        assert res_dl.status_code == 200
        assert "attachment" in res_dl.headers.get("content-disposition", "")
        assert 'filename="report.md"' in res_dl.headers.get("content-disposition", "")
        assert "text/markdown" in res_dl.headers.get("content-type", "")


def test_server_dynamic_markdown_generation(client):
    from tests.test_reporting import sample_report
    report = sample_report()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Only create JSON file
        json_file = Path(tmp_dir) / "report.json"
        json_file.write_text(report.model_dump_json())

        # Request markdown file that doesn't exist yet
        res = client.get(f"/api/reports/report.md?output_dir={tmp_dir}&download=true")
        assert res.status_code == 200
        res_dl_header = res.headers.get("content-disposition", "")
        assert "attachment" in res_dl_header
        assert 'filename="report.md"' in res_dl_header
        assert "Return ACH Test Engine Report" in res.text
        # Verify markdown file was written to disk
        assert (Path(tmp_dir) / "report.md").exists()


def test_server_report_not_found(client):
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = client.get(f"/api/reports/nonexistent.json?output_dir={tmp_dir}")
        assert res.status_code == 404
        assert res.json()["detail"] == "Report file not found"


def test_server_path_traversal_prevention(client):
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = client.get(f"/api/reports/../../etc/passwd?output_dir={tmp_dir}")
        assert res.status_code in (400, 404)


def test_server_run_and_download_flow(client, monkeypatch):
    import test_engine.server as server_mod
    from test_engine.models.result import TestExecutionResult, TestStatus
    from test_engine.models.test_case import TestCategory

    async def mock_run_test_workflow(cfg):
        result = TestExecutionResult(
            test_id="TC_01",
            name="Mock Pass",
            description="Mock test pass",
            category=TestCategory.HEALTH,
            status=TestStatus.PASS,
            http_status_code=200,
            expected_status_code=200,
            execution_time_ms=10.0,
            request_method="GET",
            request_url="http://mock/health",
        )
        return {
            "execution_results": [result.model_dump()],
            "is_reachable": True,
            "health_ok": True,
            "failure_analysis": {},
            "workflow_status": "completed",
        }

    monkeypatch.setattr(server_mod, "run_test_workflow", mock_run_test_workflow)

    with tempfile.TemporaryDirectory() as tmp_dir:
        payload = {
            "target_url": "http://mock:8000",
            "execution_mode": "mock",
            "suites": ["health"],
            "output_dir": tmp_dir,
            "report_formats": ["json", "markdown", "html"],
        }
        res = client.post("/api/run", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert "json" in data["exported_files"]
        assert "markdown" in data["exported_files"]

        # Download JSON
        dl_json = client.get(f"/api/reports/report.json?output_dir={tmp_dir}&download=true")
        assert dl_json.status_code == 200
        assert "attachment" in dl_json.headers.get("content-disposition", "")
        assert 'filename="report.json"' in dl_json.headers.get("content-disposition", "")

        # Download Markdown
        dl_md = client.get(f"/api/reports/report.md?output_dir={tmp_dir}&download=true")
        assert dl_md.status_code == 200
        assert "attachment" in dl_md.headers.get("content-disposition", "")
        assert 'filename="report.md"' in dl_md.headers.get("content-disposition", "")
        assert "Mock Pass" in dl_md.text

        # List reports
        list_res = client.get(f"/api/reports?output_dir={tmp_dir}")
        assert list_res.status_code == 200
        history = list_res.json()
        # Should have at least report.json and timestamped report
        assert len(history) >= 1
        assert any(item["filename"] == "report.json" for item in history)


