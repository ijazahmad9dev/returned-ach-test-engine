"""Tests for Phase 2: Journey Runner, Definitions, and Reporting."""

import json
from pathlib import Path

import yaml

from test_engine.journeys.models import (
    JourneyResult,
    JourneyStep,
    Persona,
    StepStatus,
)
from test_engine.reporting.exporters import JourneyReportExporter


def test_journey_definitions_yaml():
    """Verifies that definitions.yaml exists, parses, and matches Phase 2 spec."""
    defs_file = Path("test_engine/journeys/definitions.yaml")
    assert defs_file.exists(), "definitions.yaml missing"

    with defs_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "journeys" in data
    journeys = {j["id"]: j for j in data["journeys"]}
    assert "journey_1" in journeys
    assert "journey_2" in journeys
    assert "journey_3" in journeys

    # Check Journey 1 (Scenario A) expectations
    j1 = journeys["journey_1"]
    assert j1["trigger"]["return_code"] == "R01"
    assert j1["actor"]["persona"] == "marcus"
    assert j1["actor"]["role"] == "payments_specialist"
    assert j1["expectations"]["suggested_wait_business_days"] == 4
    assert j1["expectations"]["handoff_target"] == "client_payment_process"
    assert j1["expectations"]["agentos_debits_directly"] is False

    # Check Journey 2 (Retry outcome) expectations
    j2 = journeys["journey_2"]
    assert j2["expectations"]["settled"]["outcome"] == "retry_settled"
    assert j2["expectations"]["failed_again"]["outcome"] == "retry_returned"
    assert j2["expectations"]["failed_again"]["case_reopened"] is True

    # Check Journey 3 (Scenario B) expectations
    j3 = journeys["journey_3"]
    assert j3["trigger"]["return_code"] == "R03"
    assert j3["actor"]["persona"] == "priya"
    assert j3["actor"]["role"] == "reviewer"
    assert j3["expectations"]["retry_offered"] is False
    assert j3["expectations"]["on_approval_state"] == "awaiting_response"


def test_journey_report_exporter(tmp_path: Path):
    """Verifies JourneyReportExporter outputs Markdown, JSON, and Console."""
    j1 = JourneyResult(
        journey_id="journey_1",
        name="Scenario A: Insufficient Funds (R01)",
        scenario="scenario-a-insufficient-funds",
        passed=True,
        duration_seconds=5.42,
        plain_english_summary="NSF return routed to Marcus, approved and handed off.",
    )
    s1 = JourneyStep(
        step_id="J1.1",
        title="Trigger NSF return",
        persona="system",
        action_type="trigger",
        expected="Case created in awaiting_approval",
        actual="Case created with task-1",
        status=StepStatus.PASS,
    )
    s2 = JourneyStep(
        step_id="J1.2",
        title="Marcus reviews task",
        persona=Persona.MARCUS.value,
        action_type="inspect",
        expected="Suggested retry date visible",
        actual="Suggested retry date=2026-10-16",
        status=StepStatus.PASS,
        screenshot_path="/tmp/fake_shot.png",
    )
    j1.add_step(s1)
    j1.add_step(s2)

    results = [j1]

    # 1. Console render test (should not raise)
    JourneyReportExporter.render_console(results)

    # 2. Markdown export test
    md_file = tmp_path / "journey_report.md"
    JourneyReportExporter.export_markdown(results, md_file)
    assert md_file.exists()
    content = md_file.read_text(encoding="utf-8")
    assert "# Real-User Evaluation Report: Journeys 1 to 3" in content
    assert "Scenario A: Insufficient Funds (R01)" in content
    assert "fake_shot.png" in content
    assert "✅ PASS" in content

    # 3. JSON export test
    json_file = tmp_path / "journey_report.json"
    JourneyReportExporter.export_json(results, json_file)
    assert json_file.exists()
    with json_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["journey_id"] == "journey_1"
    assert data[0]["passed"] is True
    assert len(data[0]["steps"]) == 2
    assert data[0]["steps"][1]["screenshot"] == "/tmp/fake_shot.png"
