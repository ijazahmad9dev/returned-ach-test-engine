"""Tests for Phase 7: Reporting, CLI & Export System."""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from test_engine.cli import main
from test_engine.models.report import FullTestReport
from test_engine.models.result import TestExecutionResult, TestStatus
from test_engine.models.test_case import TestCategory
from test_engine.reporting.exporters import (
    HtmlExporter,
    JsonExporter,
    MarkdownExporter,
    ReportExporterManager,
)


def sample_report() -> FullTestReport:
    results = [
        TestExecutionResult(
            test_id="TC_01",
            name="Valid ACH Trigger",
            description="Tests standard trigger",
            category=TestCategory.ACH_DOMAIN,
            status=TestStatus.PASS,
            http_status_code=201,
            execution_time_ms=25.0,
            request_method="POST",
            request_url="http://localhost:8000/api/v1/triggers/returned-ach",
            expected_status_code=[200, 201],
        ),
        TestExecutionResult(
            test_id="TC_02",
            name="Missing Trace",
            description="Tests missing required trace",
            category=TestCategory.SCHEMA,
            status=TestStatus.FAIL,
            http_status_code=500,
            execution_time_ms=30.0,
            request_method="POST",
            request_url="http://localhost:8000/api/v1/triggers/returned-ach",
            expected_status_code=422,
            validation_failures=["Status code mismatch: expected 422, got 500"],
            diff_summary="• HTTP Status Mismatch: expected 422, received 500",
        ),
    ]
    return FullTestReport.from_results(
        target_url="http://localhost:8000",
        execution_mode="mock",
        results=results,
    )


def test_full_test_report_metrics():
    report = sample_report()
    summary = report.summary

    assert summary.total_tests == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.pass_rate_pct == 50.0
    assert summary.total_duration_ms == 55.0
    assert summary.has_failures is True

    assert "ach_domain" in summary.categories
    assert summary.categories["ach_domain"].passed == 1
    assert summary.categories["schema"].failed == 1


def test_json_exporter():
    report = sample_report()
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = Path(tmp_dir) / "report.json"
        exported_path = JsonExporter.export(report, json_path)

        assert exported_path.exists()
        with exported_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        loaded_report = FullTestReport.model_validate(data)
        assert loaded_report.summary.total_tests == 2
        assert loaded_report.summary.passed == 1


def test_markdown_exporter():
    report = sample_report()
    with tempfile.TemporaryDirectory() as tmp_dir:
        md_path = Path(tmp_dir) / "report.md"
        exported_path = MarkdownExporter.export(report, md_path)

        assert exported_path.exists()
        content = exported_path.read_text(encoding="utf-8")
        assert "# Return ACH Test Engine Report" in content
        assert "Total Tests" in content
        assert "TC_01" in content
        assert "Failure Diagnostics & Diffs" in content


def test_html_exporter():
    report = sample_report()
    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = Path(tmp_dir) / "report.html"
        exported_path = HtmlExporter.export(report, html_path)

        assert exported_path.exists()
        content = exported_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Return ACH Test Engine Report" in content
        assert "TC_01" in content
        assert "TC_02" in content


def test_report_exporter_manager():
    report = sample_report()
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_dir = Path(tmp_dir) / "artifacts"
        exported = ReportExporterManager.export_all(
            report=report,
            output_dir=output_dir,
            formats=["console", "json", "markdown", "html"],
        )

        assert "json" in exported
        assert "markdown" in exported
        assert "html" in exported
        assert exported["json"].exists()
        assert exported["markdown"].exists()
        assert exported["html"].exists()


def test_cli_report_command():
    report = sample_report()
    with tempfile.TemporaryDirectory() as tmp_dir:
        json_file = Path(tmp_dir) / "source_report.json"
        out_dir = Path(tmp_dir) / "out"
        JsonExporter.export(report, json_file)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["report", "--input", str(json_file), "--output-dir", str(out_dir), "--format", "markdown"],
        )
        assert result.exit_code == 0
        assert (out_dir / "report.md").exists()
