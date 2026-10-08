"""Tests for Phase 6: LangGraph Orchestration Workflow."""

import pytest

from test_engine.config import EngineConfig
from test_engine.orchestration.graph import (
    build_test_workflow,
    route_after_discovery,
    route_after_scenarios,
    run_test_workflow,
)
from test_engine.orchestration.nodes import (
    analyze_contract_node,
    analyze_failures_node,
    generate_report_node,
    generate_scenarios_node,
    validate_responses_node,
)
from test_engine.orchestration.state import TestEngineState
from tests.test_discovery import SAMPLE_OPENAPI_SPEC


def test_build_test_workflow():
    workflow = build_test_workflow()
    assert workflow is not None


def test_routing_decisions():
    # 1. After discovery
    assert route_after_discovery({"is_reachable": False}) == "generate_report"
    assert route_after_discovery({"is_reachable": True}) == "analyze_contract"

    # 2. After scenario generation
    assert route_after_scenarios({"scenarios": []}) == "generate_report"
    assert route_after_scenarios({"scenarios": [{"id": "TC1"}]}) == "execute_tests"


def test_pipeline_nodes_unit():
    config = EngineConfig(suites=["schema"])
    config_dict = config.model_dump(mode="json")

    # 1. Test analyze_contract_node
    state: TestEngineState = {
        "config_dict": config_dict,
        "raw_spec": SAMPLE_OPENAPI_SPEC,
        "health_ok": True,
    }
    update = analyze_contract_node(state)
    assert "contract_data" in update
    contract_data = update["contract_data"]
    assert len(contract_data["endpoints"]) == 3

    # 2. Test generate_scenarios_node
    state["contract_data"] = contract_data
    scenarios_update = generate_scenarios_node(state)
    assert "scenarios" in scenarios_update
    scenarios = scenarios_update["scenarios"]
    assert len(scenarios) > 0

    # 3. Test validate_responses_node & analyze_failures_node
    state["execution_results"] = [
        {
            "test_id": "TC1",
            "name": "Test 1",
            "description": "Desc 1",
            "category": "schema",
            "status": "PASS",
            "execution_time_ms": 20.0,
            "request_method": "POST",
            "request_url": "http://localhost:8000/test",
            "expected_status_code": 200,
        },
        {
            "test_id": "TC2",
            "name": "Test 2",
            "description": "Desc 2",
            "category": "schema",
            "status": "FAIL",
            "execution_time_ms": 25.0,
            "request_method": "POST",
            "request_url": "http://localhost:8000/test",
            "expected_status_code": 422,
            "validation_failures": ["Status mismatch: expected 422, got 200"],
        },
    ]

    val_update = validate_responses_node(state)
    assert val_update["workflow_status"] == "in_progress"

    diag_update = analyze_failures_node(state)
    assert "failure_analysis" in diag_update
    analysis = diag_update["failure_analysis"]
    assert analysis["total_failures"] == 1
    assert analysis["failures_by_category"]["schema"] == 1

    # 4. Test generate_report_node
    rep_update = generate_report_node(state)
    assert "report_summary" in rep_update
    summary = rep_update["report_summary"]
    assert summary["total_tests"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate_pct"] == 50.0


@pytest.mark.asyncio
async def test_full_workflow_unreachable_early_exit():
    # If target is unreachable port/server, should exit early to report
    config = EngineConfig(
        target_url="http://127.0.0.1:59999",  # Non-existent local port
        timeout_seconds=0.5,
    )
    final_state = await run_test_workflow(config)

    assert final_state["workflow_status"] == "unreachable"
    assert final_state["is_reachable"] is False
    assert final_state["report_summary"]["total_tests"] == 0
