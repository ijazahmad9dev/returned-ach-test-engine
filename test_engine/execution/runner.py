"""Test Runner and Concurrency Controller."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from test_engine.config import EngineConfig
from test_engine.execution.client import ExecutionHttpClient, ExecutionResponse
from test_engine.logger import get_logger, trace_context
from test_engine.models.result import TestExecutionResult, TestStatus
from test_engine.models.test_case import TestCase
from test_engine.validation.validator import ResponseValidator

logger = get_logger("execution.runner")


class TestRunner:
    """Orchestrates concurrent and sequential execution of test scenarios."""
    __test__ = False

    def __init__(
        self,
        config: EngineConfig,
        http_client: ExecutionHttpClient | None = None,
        validator: ResponseValidator | None = None,
    ) -> None:
        self.config = config
        self.client = http_client or ExecutionHttpClient(config)
        self.validator = validator or ResponseValidator()

    async def run_scenario(
        self, test_case: TestCase, context: dict[str, Any] | None = None
    ) -> tuple[TestExecutionResult, dict[str, Any]]:
        """Executes a single test case within a scoped trace context and validates outcome."""
        context = dict(context or {})

        # Resolve dynamic variables in path, params, and body from scenario context
        req_path = self._substitute_vars(test_case.request.path, context)
        req_params = {k: self._substitute_vars(v, context) for k, v in test_case.request.params.items()}
        req_body = self._substitute_vars(test_case.request.json_body, context)

        full_url = f"{self.config.base_url}{req_path}"

        with trace_context(test_case.id) as tracer:
            tracer.record("INFO", f"Executing {test_case.name} [{test_case.method} {req_path}]")

            # Execute HTTP request
            resp = await self.client.execute(
                method=test_case.request.method,
                path=req_path,
                params=req_params,
                headers=test_case.request.headers,
                json_body=req_body,
                raw_body=test_case.request.raw_body,
            )
            tracer.record("INFO", f"Response: HTTP {resp.status_code} in {resp.latency_ms}ms")

            # Validate response
            status, failures, outcomes, diff = self.validator.validate(test_case, resp)

            # Extract any context variables from response for subsequent steps
            if test_case.context_extractors and isinstance(resp.json_body, dict):
                for var_name, key_path in test_case.context_extractors.items():
                    if key_path in resp.json_body:
                        context[var_name] = resp.json_body[key_path]
                        tracer.record("INFO", f"Extracted context {var_name}={context[var_name]}")
                    elif "." in key_path:
                        parts = key_path.split(".")
                        curr = resp.json_body
                        for p in parts:
                            if isinstance(curr, dict) and p in curr:
                                curr = curr[p]
                            else:
                                curr = None
                                break
                        if curr is not None:
                            context[var_name] = curr
                            tracer.record("INFO", f"Extracted context {var_name}={context[var_name]}")
                    elif var_name in resp.json_body:
                        context[var_name] = resp.json_body[var_name]
                        tracer.record("INFO", f"Extracted context {var_name}={context[var_name]}")
                    elif "id" in resp.json_body and var_name.endswith("_id"):
                        context[var_name] = resp.json_body["id"]
                        tracer.record("INFO", f"Extracted context {var_name}={context[var_name]}")

            result = TestExecutionResult(
                test_id=test_case.id,
                name=test_case.name,
                description=test_case.description,
                category=test_case.category,
                status=status,
                http_status_code=resp.status_code,
                execution_time_ms=resp.latency_ms,
                request_method=test_case.request.method,
                request_url=full_url,
                request_headers=test_case.request.headers,
                request_body=req_body or test_case.request.raw_body,
                response_headers=resp.headers,
                response_body=resp.json_body,
                response_raw_text=resp.text,
                expected_status_code=test_case.expected.status_code,
                expected_error_code=test_case.expected.expected_error_code,
                validation_failures=failures,
                validation_details=outcomes,
                diff_summary=diff,
                error_info=resp.error,
                logs=tracer.formatted_logs(),
            )

        return result, context

    async def run_all(self, test_cases: list[TestCase]) -> list[TestExecutionResult]:
        """Runs test cases: concurrent for independent tests, sequential for stateful workflows."""
        results: list[TestExecutionResult] = []

        # Separate independent vs stateful/sequential cases
        independent_cases: list[TestCase] = []
        stateful_cases: list[TestCase] = []

        for tc in test_cases:
            if tc.is_stateful:
                stateful_cases.append(tc)
            else:
                independent_cases.append(tc)

        # 1. Run independent cases with semaphore-controlled concurrency
        semaphore = asyncio.Semaphore(self.config.max_concurrency)

        async def _bounded_run(tc: TestCase) -> TestExecutionResult:
            async with semaphore:
                res, _ = await self.run_scenario(tc)
                return res

        logger.info(f"Running {len(independent_cases)} independent test scenarios with concurrency={self.config.max_concurrency}...")
        independent_results = await asyncio.gather(*[_bounded_run(tc) for tc in independent_cases])
        results.extend(independent_results)

        # 2. Run stateful cases in sequential order respecting steps
        logger.info(f"Running {len(stateful_cases)} stateful/lifecycle test scenarios sequentially...")
        stateful_cases.sort(key=lambda x: (x.depends_on or "", x.step_number or 0))

        scenario_context: dict[str, Any] = {}
        for tc in stateful_cases:
            res, scenario_context = await self.run_scenario(tc, scenario_context)
            results.append(res)

        logger.info(
            f"Execution finished: {len(results)} total tests "
            f"(Passed: {sum(1 for r in results if r.status == TestStatus.PASS)}, "
            f"Failed: {sum(1 for r in results if r.status == TestStatus.FAIL)}, "
            f"Errors: {sum(1 for r in results if r.status == TestStatus.ERROR)})"
        )
        return results

    def _substitute_vars(self, obj: Any, context: dict[str, Any]) -> Any:
        """Recursively substitutes {var_name} templates with values from scenario context."""
        if isinstance(obj, str):
            for k, v in context.items():
                obj = obj.replace(f"{{{k}}}", str(v))

            # Fallback for any remaining unpopulated template placeholders like {case_id} or {task_id}
            def _fallback_replace(match: re.Match[str]) -> str:
                var_name = match.group(1).lower()
                if "uuid" in var_name or var_name.endswith("_id") or var_name == "id":
                    return "00000000-0000-0000-0000-000000000001"
                if var_name in ("template", "workflow"):
                    return "returned-ach"
                if var_name == "system":
                    return "payment"
                if "hash" in var_name:
                    return "cf4e712994ef7a6ccdebdbd55c1733dedb95f1c9f6067e42dfc55e369b58ef06"
                return match.group(0)

            obj = re.sub(r"\{([a-zA-Z0-9_]+)\}", _fallback_replace, obj)
            return obj
        elif isinstance(obj, dict):
            return {k: self._substitute_vars(v, context) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._substitute_vars(item, context) for item in obj]
        return obj

    async def close(self) -> None:
        """Closes HTTP client resources."""
        await self.client.close()
