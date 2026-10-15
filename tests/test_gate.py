"""Unit and integration tests for Phase 4: Gate and Evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from test_engine.cli import main
from test_engine.gate.runner import DeploymentGateRunner, GateExecutionSummary
from test_engine.journeys.models import JourneyResult, JourneyStep, StepStatus
from test_engine.reporting.client_packager import (
    OPEN_POLICY_QUESTIONS,
    ClientEvidencePackager,
)


@pytest.fixture
def mock_passing_journey_results(tmp_path: Path) -> list[JourneyResult]:
    """Generates a complete mock set of 8 passing journeys with screenshots."""
    shots_dir = tmp_path / "mock_shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_file = shots_dir / "sample_screen.png"
    shot_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

    results: list[JourneyResult] = []
    for i in range(1, 9):
        j_id = f"journey_{i}"
        res = JourneyResult(
            journey_id=j_id,
            name=f"Mock Journey {i}",
            scenario=f"mock-scenario-{i}",
            passed=True,
            duration_seconds=1.25,
            plain_english_summary=f"Journey {i} passed verification.",
        )
        res.add_step(
            JourneyStep(
                step_id=f"step_{i}_1",
                title=f"Step 1 for {j_id}",
                persona="marcus" if i == 1 else "priya",
                action_type="inspect",
                expected="Target state verified",
                actual="Target state verified",
                status=StepStatus.PASS,
                screenshot_path=str(shot_file),
            )
        )
        results.append(res)
    return results


@pytest.fixture
def mock_failing_journey_results(mock_passing_journey_results: list[JourneyResult]) -> list[JourneyResult]:
    """Generates a mock set of journeys where Journey 4 (suspected fraud) fails."""
    results = [r for r in mock_passing_journey_results]
    failing_j4 = JourneyResult(
        journey_id="journey_4",
        name="Journey 4: Suspected Fraud (R10)",
        scenario="suspected-fraud",
        passed=False,
        duration_seconds=2.1,
        plain_english_summary="Urgent fraud notification missing from analyst inbox.",
    )
    failing_j4.add_step(
        JourneyStep(
            step_id="j4_step_2",
            title="Inspect inbox for urgent fraud task",
            persona="sam",
            action_type="inspect",
            expected="Task with priority 'urgent'",
            actual="Task not found in inbox",
            status=StepStatus.FAIL,
        )
    )
    results[3] = failing_j4
    return results


# -----------------------------------------------------------------------------
# 1. Tests for Pre-Flight Health Checks
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preflight_health_all_ok():
    runner = DeploymentGateRunner(runtime_url="http://mock-api:8000", ui_url="http://mock-ui:3000")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp_api = MagicMock()
        mock_resp_api.status_code = 200
        mock_resp_api.headers = {"content-type": "application/json"}
        mock_resp_api.json.return_value = {"status": "ok"}

        mock_resp_ui = MagicMock()
        mock_resp_ui.status_code = 200

        mock_get.side_effect = [mock_resp_api, mock_resp_ui]

        healthy, details = await runner.check_preflight_health()
        assert healthy is True
        assert details["api_healthy"] is True
        assert details["ui_healthy"] is True
        assert details["errors"] == []


@pytest.mark.asyncio
async def test_preflight_health_api_down():
    runner = DeploymentGateRunner(runtime_url="http://mock-api:8000", ui_url="http://mock-ui:3000")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [Exception("Connection refused"), MagicMock(status_code=200)]

        healthy, details = await runner.check_preflight_health()
        assert healthy is False
        assert details["api_healthy"] is False
        assert any("Failed to connect" in err for err in details["errors"])


@pytest.mark.asyncio
async def test_preflight_health_ui_500():
    runner = DeploymentGateRunner(runtime_url="http://mock-api:8000", ui_url="http://mock-ui:3000")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp_api = MagicMock(status_code=200, headers={"content-type": "application/json"}, json=lambda: {"status": "ok"})
        mock_resp_ui = MagicMock(status_code=500)
        mock_get.side_effect = [mock_resp_api, mock_resp_ui]

        healthy, details = await runner.check_preflight_health()
        assert healthy is False
        assert details["ui_healthy"] is False
        assert any("HTTP 500" in err for err in details["errors"])


# -----------------------------------------------------------------------------
# 2. Tests for DeploymentGateRunner & Red Deploy Behavior
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gate_runner_green_deploy(tmp_path: Path, mock_passing_journey_results: list[JourneyResult]):
    """Verifies that when all journeys pass, the gate cleanly passes (exit code 0)."""
    out_dir = tmp_path / "gate_reports"
    runner = DeploymentGateRunner(output_dir=out_dir, headless=True, bundle_client_report=True)

    with patch.object(runner, "check_preflight_health", new_callable=AsyncMock) as mock_preflight, \
         patch("test_engine.gate.runner.BrowserDriver") as mock_driver_cls, \
         patch("test_engine.gate.runner.JourneyRunner") as mock_runner_cls:

        mock_preflight.return_value = (True, {"healthy": True, "api_healthy": True, "ui_healthy": True})
        mock_driver = MagicMock()
        mock_driver.__aenter__ = AsyncMock(return_value=mock_driver)
        mock_driver.__aexit__ = AsyncMock(return_value=None)
        mock_driver_cls.return_value = mock_driver

        mock_jr = MagicMock()
        mock_jr.run_journey_1 = AsyncMock(return_value=mock_passing_journey_results[0])
        mock_jr.run_journey_2 = AsyncMock(return_value=mock_passing_journey_results[1])
        mock_jr.run_journey_3 = AsyncMock(return_value=mock_passing_journey_results[2])
        mock_jr.run_journey_4 = AsyncMock(return_value=mock_passing_journey_results[3])
        mock_jr.run_journey_5 = AsyncMock(return_value=mock_passing_journey_results[4])
        mock_jr.run_journey_6 = AsyncMock(return_value=mock_passing_journey_results[5])
        mock_jr.run_journey_7 = AsyncMock(return_value=mock_passing_journey_results[6])
        mock_jr.run_journey_8 = AsyncMock(return_value=mock_passing_journey_results[7])
        mock_runner_cls.return_value = mock_jr

        summary = await runner.run_gate()

        assert summary.deploy_passed is True
        assert summary.exit_code == 0
        assert summary.total_journeys == 8
        assert summary.passed_journeys == 8
        assert summary.failed_journeys == 0
        assert summary.failure_reasons == []
        assert summary.client_package_dir is not None
        assert (summary.client_package_dir / "index.html").exists()
        assert (summary.client_package_dir / "evidence_manifest.json").exists()


@pytest.mark.asyncio
async def test_gate_runner_red_deploy_on_journey_failure(tmp_path: Path, mock_failing_journey_results: list[JourneyResult]):
    """Verifies that if any journey fails, the gate strictly rejects the deploy (exit code 1)."""
    out_dir = tmp_path / "gate_reports"
    runner = DeploymentGateRunner(output_dir=out_dir, headless=True, bundle_client_report=True)

    with patch.object(runner, "check_preflight_health", new_callable=AsyncMock) as mock_preflight, \
         patch("test_engine.gate.runner.BrowserDriver") as mock_driver_cls, \
         patch("test_engine.gate.runner.JourneyRunner") as mock_runner_cls:

        mock_preflight.return_value = (True, {"healthy": True, "api_healthy": True, "ui_healthy": True})
        mock_driver = MagicMock()
        mock_driver.__aenter__ = AsyncMock(return_value=mock_driver)
        mock_driver.__aexit__ = AsyncMock(return_value=None)
        mock_driver_cls.return_value = mock_driver

        mock_jr = MagicMock()
        mock_jr.run_journey_1 = AsyncMock(return_value=mock_failing_journey_results[0])
        mock_jr.run_journey_2 = AsyncMock(return_value=mock_failing_journey_results[1])
        mock_jr.run_journey_3 = AsyncMock(return_value=mock_failing_journey_results[2])
        mock_jr.run_journey_4 = AsyncMock(return_value=mock_failing_journey_results[3])
        mock_jr.run_journey_5 = AsyncMock(return_value=mock_failing_journey_results[4])
        mock_jr.run_journey_6 = AsyncMock(return_value=mock_failing_journey_results[5])
        mock_jr.run_journey_7 = AsyncMock(return_value=mock_failing_journey_results[6])
        mock_jr.run_journey_8 = AsyncMock(return_value=mock_failing_journey_results[7])
        mock_runner_cls.return_value = mock_jr

        summary = await runner.run_gate()

        assert summary.deploy_passed is False
        assert summary.exit_code == 1
        assert summary.failed_journeys == 1
        assert len(summary.failure_reasons) > 0
        assert any("journey_4" in r for r in summary.failure_reasons)
        assert summary.red_deploy_report_path is not None
        assert summary.red_deploy_report_path.exists()

        # Check content of red_deploy_failure.json
        with summary.red_deploy_report_path.open("r", encoding="utf-8") as f:
            red_data = json.load(f)
            assert red_data["deployment_verdict"] == "REJECTED_RED_DEPLOY"
            assert len(red_data["failed_journeys"]) == 1
            assert red_data["failed_journeys"][0]["journey_id"] == "journey_4"


@pytest.mark.asyncio
async def test_gate_runner_red_deploy_on_preflight_fail(tmp_path: Path):
    """Verifies that an unreachable service causes instant red deploy rejection without executing journeys."""
    out_dir = tmp_path / "gate_reports"
    runner = DeploymentGateRunner(output_dir=out_dir)

    with patch.object(runner, "check_preflight_health", new_callable=AsyncMock) as mock_preflight:
        mock_preflight.return_value = (False, {"healthy": False, "errors": ["Runtime API returned 503"]})

        summary = await runner.run_gate()

        assert summary.deploy_passed is False
        assert summary.exit_code == 1
        assert summary.preflight_ok is False
        assert summary.total_journeys == 0
        assert (out_dir / "red_deploy_failure.json").exists()
        assert (out_dir / "red_deploy_failure.md").exists()


# -----------------------------------------------------------------------------
# 3. Tests for ClientEvidencePackager
# -----------------------------------------------------------------------------

def test_client_evidence_packager(tmp_path: Path, mock_passing_journey_results: list[JourneyResult]):
    """Verifies that ClientEvidencePackager produces all required artifacts with cryptographic hashes."""
    out_dir = tmp_path / "package_out"
    preflight = {"healthy": True, "api_healthy": True, "ui_healthy": True}

    bundle = ClientEvidencePackager.package(
        output_dir=out_dir,
        journey_results=mock_passing_journey_results,
        preflight_info=preflight,
        runtime_url="http://localhost:8000",
        ui_url="http://localhost:3000",
        is_deploy_passed=True,
    )

    pkg_dir = bundle["package_dir"]
    assert pkg_dir.exists()
    assert bundle["markdown"].exists()
    assert bundle["html"].exists()
    assert bundle["manifest"].exists()

    # Verify Markdown contents
    md_text = bundle["markdown"].read_text(encoding="utf-8")
    assert "AgentOS Return ACH Platform - Client Acceptance & Deployment Gate Report" in md_text
    assert "✅ APPROVED / PASSED" in md_text
    assert "Formal Client Sign-Off Section" in md_text
    assert "Open Questions & Policy Ambiguities" in md_text
    assert "R16 and R20 have no rule in the AgentOS policy" in md_text

    # Verify HTML contents
    html_text = bundle["html"].read_text(encoding="utf-8")
    assert "DEPLOY APPROVED" in html_text
    assert "NACHA &amp; Client Core Requirements Scorecard" in html_text or "NACHA & Client Core Requirements Scorecard" in html_text
    assert "Formal Client Sign-Off &amp; Acceptance Block" in html_text or "Formal Client Sign-Off & Acceptance Block" in html_text

    # Verify Manifest and SHA-256 Checksums
    with bundle["manifest"].open("r", encoding="utf-8") as f:
        manifest = json.load(f)
        assert manifest["evaluation_verdict"] == "PASSED"
        assert manifest["total_journeys"] == 8
        assert manifest["passed_journeys"] == 8
        assert manifest["open_policy_questions_count"] == len(OPEN_POLICY_QUESTIONS)
        checksums = manifest["sha256_checksums"]
        assert len(checksums) >= 2  # md and html, plus screenshots

        # Confirm that computed checksum matches actual file content
        for rel_path, expected_hash in checksums.items():
            actual_file = pkg_dir / rel_path
            assert actual_file.exists(), f"Manifest lists {rel_path} but it is missing"
            calculated_hash = hashlib.sha256(actual_file.read_bytes()).hexdigest()
            assert calculated_hash == expected_hash, f"Hash mismatch for {rel_path}"


# -----------------------------------------------------------------------------
# 4. Tests for CLI `ach-test gate` Command
# -----------------------------------------------------------------------------

def test_cli_gate_command_success(mock_passing_journey_results: list[JourneyResult]):
    """Verifies that ach-test gate exits 0 on success."""
    runner = CliRunner()

    with patch("test_engine.gate.runner.DeploymentGateRunner.run_gate", new_callable=AsyncMock) as mock_run_gate:
        mock_run_gate.return_value = GateExecutionSummary(
            deploy_passed=True,
            exit_code=0,
            preflight_ok=True,
            preflight_details={"healthy": True},
            total_journeys=8,
            passed_journeys=8,
            failed_journeys=0,
            journey_results=mock_passing_journey_results,
        )

        res = runner.invoke(main, ["gate", "--url", "http://localhost:8000", "--ui-url", "http://localhost:3000"])
        assert res.exit_code == 0


def test_cli_gate_command_failure():
    """Verifies that ach-test gate exits 1 on red deploy failure."""
    runner = CliRunner()

    with patch("test_engine.gate.runner.DeploymentGateRunner.run_gate", new_callable=AsyncMock) as mock_run_gate:
        mock_run_gate.return_value = GateExecutionSummary(
            deploy_passed=False,
            exit_code=1,
            preflight_ok=False,
            preflight_details={"healthy": False},
            total_journeys=0,
            passed_journeys=0,
            failed_journeys=0,
            failure_reasons=["Target runtime API returned 503 Service Unavailable"],
        )

        res = runner.invoke(main, ["gate", "--url", "http://localhost:8000"])
        assert res.exit_code == 1
