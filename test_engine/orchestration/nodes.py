"""LangGraph pipeline node implementations for the testing workflow."""

from __future__ import annotations

import collections
from typing import Any

from test_engine.config import EngineConfig
from test_engine.discovery.contract_analyzer import ContractAnalyzer
from test_engine.discovery.openapi_fetcher import OpenApiFetcher
from test_engine.discovery.resolver import TargetResolver
from test_engine.execution.runner import TestRunner
from test_engine.logger import get_logger
from test_engine.models.contract import ApiContract
from test_engine.models.result import TestExecutionResult, TestStatus
from test_engine.models.test_case import TestCase
from test_engine.orchestration.state import TestEngineState
from test_engine.scenarios.generator import ScenarioGenerator

logger = get_logger("orchestration.nodes")


async def discover_api_node(state: TestEngineState) -> dict[str, Any]:
    """Node 1: Connects to target URL, probes reachability, health, and fetches OpenAPI spec."""
    cfg = EngineConfig(**state.get("config_dict", {}))
    logger.info(f"[Node: discover_api] Probing target: {cfg.target_url}")

    resolver = TargetResolver(cfg)
    resolution = await resolver.resolve()

    if not resolution.is_reachable:
        logger.warning(f"Target unreachable: {cfg.target_url}")
        return {
            "is_reachable": False,
            "health_ok": False,
            "workflow_status": "unreachable",
            "error_message": resolution.error_message or "Target server is unreachable",
        }

    raw_spec = None
    if resolution.openapi_url:
        fetcher = OpenApiFetcher(timeout_seconds=cfg.timeout_seconds)
        try:
            raw_spec = await fetcher.fetch(resolution.openapi_url)
        except Exception as e:
            logger.warning(f"Failed to fetch OpenAPI spec from {resolution.openapi_url}: {e}")

    return {
        "is_reachable": True,
        "health_ok": resolution.health_ok,
        "openapi_url": resolution.openapi_url,
        "raw_spec": raw_spec,
        "workflow_status": "in_progress",
    }


def analyze_contract_node(state: TestEngineState) -> dict[str, Any]:
    """Node 2: Analyzes OpenAPI specification and builds ApiContract model."""
    cfg = EngineConfig(**state.get("config_dict", {}))
    raw_spec = state.get("raw_spec")
    analyzer = ContractAnalyzer()

    logger.info(f"[Node: analyze_contract] Analyzing API contract for {cfg.target_url}...")
    if raw_spec:
        contract = analyzer.analyze(
            spec=raw_spec,
            base_url=cfg.base_url,
            target_url=cfg.target_url,
            is_single_endpoint_mode=cfg.is_specific_endpoint,
            single_path=cfg.specific_endpoint_path,
            health_ok=state.get("health_ok", False),
        )
    else:
        contract = analyzer.create_fallback_contract(
            base_url=cfg.base_url,
            target_url=cfg.target_url,
            endpoint_path=cfg.specific_endpoint_path or "/api/v1/health",
            health_ok=state.get("health_ok", False),
        )

    logger.info(f"Discovered {len(contract.endpoints)} endpoints in contract.")
    return {"contract_data": contract.model_dump(mode="json")}


def generate_scenarios_node(state: TestEngineState) -> dict[str, Any]:
    """Node 3: Generates test scenarios based on contract and configured test suites."""
    cfg = EngineConfig(**state.get("config_dict", {}))
    contract_data = state.get("contract_data", {})
    contract = ApiContract.model_validate(contract_data)

    logger.info(f"[Node: generate_scenarios] Generating test cases across suites {cfg.suites}...")
    generator = ScenarioGenerator()
    test_cases = generator.generate_all(contract, cfg)

    logger.info(f"Generated {len(test_cases)} total test cases.")
    return {"scenarios": [tc.model_dump(mode="json") for tc in test_cases]}


async def execute_tests_node(state: TestEngineState) -> dict[str, Any]:
    """Node 4: Executes test scenarios through asynchronous test runner."""
    cfg = EngineConfig(**state.get("config_dict", {}))
    raw_scenarios = state.get("scenarios", [])
    test_cases = [TestCase.model_validate(s) for s in raw_scenarios]

    logger.info(f"[Node: execute_tests] Executing {len(test_cases)} test scenarios...")
    runner = TestRunner(cfg)
    try:
        results = await runner.run_all(test_cases)
    finally:
        await runner.close()

    return {"execution_results": [r.model_dump(mode="json") for r in results]}


def validate_responses_node(state: TestEngineState) -> dict[str, Any]:
    """Node 5: Validates aggregated results and checks for execution integrity."""
    raw_results = state.get("execution_results", [])
    results = [TestExecutionResult.model_validate(r) for r in raw_results]

    passed_count = sum(1 for r in results if r.status == TestStatus.PASS)
    failed_count = sum(1 for r in results if r.status == TestStatus.FAIL)
    error_count = sum(1 for r in results if r.status == TestStatus.ERROR)

    logger.info(
        f"[Node: validate_responses] Completed validation: "
        f"{passed_count} PASS, {failed_count} FAIL, {error_count} ERROR out of {len(results)}"
    )
    return {"workflow_status": "in_progress"}


def analyze_failures_node(state: TestEngineState) -> dict[str, Any]:
    """Node 6: Diagnoses failures, clusters errors by category, and isolates root causes."""
    raw_results = state.get("execution_results", [])
    results = [TestExecutionResult.model_validate(r) for r in raw_results]

    failures_by_category: dict[str, int] = collections.defaultdict(int)
    failures_by_endpoint: dict[str, int] = collections.defaultdict(int)
    common_failure_reasons: list[str] = []

    for r in results:
        if r.status in (TestStatus.FAIL, TestStatus.ERROR):
            failures_by_category[r.category.value] += 1
            failures_by_endpoint[r.request_url] += 1
            if r.validation_failures:
                common_failure_reasons.extend(r.validation_failures[:2])
            elif r.error_info:
                common_failure_reasons.append(r.error_info)

    analysis = {
        "total_failures": sum(failures_by_category.values()),
        "failures_by_category": dict(failures_by_category),
        "failures_by_endpoint": dict(failures_by_endpoint),
        "sample_failure_reasons": common_failure_reasons[:10],
    }
    logger.info(f"[Node: analyze_failures] Identified {analysis['total_failures']} total failures.")
    return {"failure_analysis": analysis}


def generate_report_node(state: TestEngineState) -> dict[str, Any]:
    """Node 7: Compiles final summary metrics for report generation."""
    raw_results = state.get("execution_results", [])
    results = [TestExecutionResult.model_validate(r) for r in raw_results]

    total = len(results)
    passed = sum(1 for r in results if r.status == TestStatus.PASS)
    failed = sum(1 for r in results if r.status == TestStatus.FAIL)
    errors = sum(1 for r in results if r.status == TestStatus.ERROR)
    skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
    total_time_ms = round(sum(r.execution_time_ms for r in results), 2)
    pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0

    summary = {
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "pass_rate_pct": pass_rate,
        "total_duration_ms": total_time_ms,
        "is_reachable": state.get("is_reachable", False),
        "health_ok": state.get("health_ok", False),
    }

    status = "completed"
    if not state.get("is_reachable", True):
        status = "unreachable"
    elif errors > 0 and passed == 0:
        status = "error"

    logger.info(f"[Node: generate_report] Summary: {passed}/{total} passed ({pass_rate}%) in {total_time_ms}ms")
    return {
        "report_summary": summary,
        "workflow_status": status,
    }
