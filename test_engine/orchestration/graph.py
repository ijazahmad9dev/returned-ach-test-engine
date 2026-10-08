"""LangGraph Testing Workflow Assembly and Conditional Routing."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from test_engine.config import EngineConfig
from test_engine.logger import get_logger
from test_engine.orchestration.nodes import (
    analyze_contract_node,
    analyze_failures_node,
    discover_api_node,
    execute_tests_node,
    generate_report_node,
    generate_scenarios_node,
    validate_responses_node,
)
from test_engine.orchestration.state import TestEngineState

logger = get_logger("orchestration.graph")


def route_after_discovery(state: TestEngineState) -> Literal["analyze_contract", "generate_report"]:
    """Routes to contract analysis if reachable, or bypasses directly to report if unreachable."""
    if not state.get("is_reachable", False):
        logger.warning("Routing condition: Target is unreachable -> bypassing to generate_report")
        return "generate_report"
    return "analyze_contract"


def route_after_scenarios(state: TestEngineState) -> Literal["execute_tests", "generate_report"]:
    """Routes to test execution if scenarios exist, or to report if zero scenarios generated."""
    scenarios = state.get("scenarios", [])
    if not scenarios:
        logger.warning("Routing condition: No test scenarios generated -> bypassing to generate_report")
        return "generate_report"
    return "execute_tests"


def build_test_workflow() -> Any:
    """Constructs and compiles the LangGraph StateGraph testing orchestration workflow."""
    workflow = StateGraph(TestEngineState)

    # Register workflow nodes
    workflow.add_node("discover_api", discover_api_node)
    workflow.add_node("analyze_contract", analyze_contract_node)
    workflow.add_node("generate_scenarios", generate_scenarios_node)
    workflow.add_node("execute_tests", execute_tests_node)
    workflow.add_node("validate_responses", validate_responses_node)
    workflow.add_node("analyze_failures", analyze_failures_node)
    workflow.add_node("generate_report", generate_report_node)

    # Define edges and conditional transitions
    workflow.add_edge(START, "discover_api")

    workflow.add_conditional_edges(
        "discover_api",
        route_after_discovery,
        {
            "analyze_contract": "analyze_contract",
            "generate_report": "generate_report",
        },
    )

    workflow.add_edge("analyze_contract", "generate_scenarios")

    workflow.add_conditional_edges(
        "generate_scenarios",
        route_after_scenarios,
        {
            "execute_tests": "execute_tests",
            "generate_report": "generate_report",
        },
    )

    workflow.add_edge("execute_tests", "validate_responses")
    workflow.add_edge("validate_responses", "analyze_failures")
    workflow.add_edge("analyze_failures", "generate_report")
    workflow.add_edge("generate_report", END)

    compiled = workflow.compile()
    logger.info("Compiled LangGraph Return ACH Test Workflow successfully.")
    return compiled


async def run_test_workflow(config: EngineConfig) -> TestEngineState:
    """Executes the full compiled LangGraph testing workflow for a target configuration."""
    graph = build_test_workflow()

    initial_state: TestEngineState = {
        "target_url": config.target_url,
        "config_dict": config.model_dump(mode="json"),
        "is_reachable": False,
        "health_ok": False,
        "workflow_status": "initialized",
    }

    logger.info(f"Starting LangGraph testing pipeline for target: {config.target_url}")
    final_state = await graph.ainvoke(initial_state)
    logger.info(
        f"Completed LangGraph testing pipeline (status='{final_state.get('workflow_status')}')"
    )
    return final_state
