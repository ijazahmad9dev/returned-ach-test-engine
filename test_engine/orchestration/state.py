"""State schema for LangGraph test execution workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class TestEngineState(TypedDict, total=False):
    """Workflow state dictionary flowing through LangGraph testing nodes."""
    __test__ = False

    # Input target and runtime configuration
    target_url: str
    config_dict: dict[str, Any]

    # Target discovery outcomes
    is_reachable: bool
    health_ok: bool
    openapi_url: str | None
    raw_spec: dict[str, Any] | None

    # Discovered contract & schema model (dict representation of ApiContract)
    contract_data: dict[str, Any] | None

    # Generated test scenarios (list of dicts from TestCase.model_dump())
    scenarios: list[dict[str, Any]]

    # Execution results (list of dicts from TestExecutionResult.model_dump())
    execution_results: list[dict[str, Any]]

    # Failure diagnosis and clustered analysis
    failure_analysis: dict[str, Any]

    # Final summary metrics and report outputs
    report_summary: dict[str, Any]

    # Lifecycle status
    workflow_status: str  # "initialized", "in_progress", "completed", "unreachable", "error"
    error_message: str | None
