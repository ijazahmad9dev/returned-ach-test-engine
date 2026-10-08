"""Multi-Dimensional Response Validator."""

from __future__ import annotations

from typing import Any

from test_engine.execution.client import ExecutionResponse
from test_engine.models.result import TestStatus, ValidationOutcome
from test_engine.models.test_case import TestCase
from test_engine.validation.diff_analyzer import DiffAnalyzer


class ResponseValidator:
    """Evaluates HTTP execution responses against expected criteria in TestCase."""

    def __init__(self, diff_analyzer: DiffAnalyzer | None = None) -> None:
        self.diff_analyzer = diff_analyzer or DiffAnalyzer()

    def validate(
        self, test_case: TestCase, response: ExecutionResponse
    ) -> tuple[TestStatus, list[str], list[ValidationOutcome], str | None]:
        """Validates response against TestCase.expected; returns (status, failures, outcomes, diff)."""
        expected = test_case.expected
        outcomes: list[ValidationOutcome] = []
        failures: list[str] = []

        # 1. HTTP Status Code validation
        status_passed = False
        if isinstance(expected.status_code, list):
            status_passed = response.status_code in expected.status_code
        else:
            status_passed = response.status_code == expected.status_code

        outcomes.append(
            ValidationOutcome(
                rule_name="http_status_code",
                passed=status_passed,
                expected=expected.status_code,
                actual=response.status_code,
                message=f"HTTP status {response.status_code} matches expected {expected.status_code}"
                if status_passed
                else f"HTTP status {response.status_code} does not match expected {expected.status_code}",
            )
        )
        if not status_passed:
            failures.append(
                f"HTTP status code mismatch: expected {expected.status_code}, got {response.status_code}"
            )

        # 2. Performance / Latency SLA validation
        if expected.max_latency_ms is not None:
            latency_passed = response.latency_ms <= expected.max_latency_ms
            outcomes.append(
                ValidationOutcome(
                    rule_name="latency_sla",
                    passed=latency_passed,
                    expected=f"<={expected.max_latency_ms}ms",
                    actual=f"{response.latency_ms}ms",
                    message="Response latency within threshold"
                    if latency_passed
                    else f"Response latency {response.latency_ms}ms exceeded {expected.max_latency_ms}ms",
                )
            )
            if not latency_passed:
                failures.append(
                    f"Latency {response.latency_ms}ms exceeded maximum allowed {expected.max_latency_ms}ms"
                )

        # 3. Expected Keys in Response
        missing_keys: list[str] = []
        if expected.expected_keys and isinstance(response.json_body, dict):
            for k in expected.expected_keys:
                if k not in response.json_body:
                    missing_keys.append(k)

            keys_passed = len(missing_keys) == 0
            outcomes.append(
                ValidationOutcome(
                    rule_name="required_keys",
                    passed=keys_passed,
                    expected=expected.expected_keys,
                    actual=list(response.json_body.keys()),
                    message="All required response keys present"
                    if keys_passed
                    else f"Missing required keys: {missing_keys}",
                )
            )
            if not keys_passed:
                failures.append(f"Missing expected response keys: {missing_keys}")

        # 4. Error Envelope validation (for 4xx/5xx responses or explicit error tests)
        actual_error_code, actual_field_paths = self.diff_analyzer.extract_error_info(response.json_body)

        if expected.expected_error_code:
            code_passed = (
                actual_error_code.lower() == expected.expected_error_code.lower()
                if actual_error_code
                else False
            )
            outcomes.append(
                ValidationOutcome(
                    rule_name="error_envelope_code",
                    passed=code_passed,
                    expected=expected.expected_error_code,
                    actual=actual_error_code,
                    message=f"Error code matches '{expected.expected_error_code}'"
                    if code_passed
                    else f"Expected error code '{expected.expected_error_code}', got '{actual_error_code}'",
                )
            )
            if not code_passed:
                failures.append(
                    f"Expected error code '{expected.expected_error_code}', received '{actual_error_code}'"
                )

        # 5. Field Error validation
        if expected.expected_error_field:
            # Check if any path in actual_field_paths ends with or equals the field name
            field_matched = any(
                p == expected.expected_error_field or p.endswith(f".{expected.expected_error_field}")
                for p in actual_field_paths
            )
            outcomes.append(
                ValidationOutcome(
                    rule_name="field_level_error",
                    passed=field_matched,
                    expected=expected.expected_error_field,
                    actual=actual_field_paths,
                    message=f"Field error found for '{expected.expected_error_field}'"
                    if field_matched
                    else f"Expected error field '{expected.expected_error_field}' not found in {actual_field_paths}",
                )
            )
            if not field_matched:
                failures.append(
                    f"Expected field-level validation error for '{expected.expected_error_field}', received {actual_field_paths}"
                )

        # Determine overall test status
        if response.error:
            test_status = TestStatus.ERROR
        elif len(failures) == 0:
            test_status = TestStatus.PASS
        else:
            test_status = TestStatus.FAIL

        # Build diff summary if there were failures
        diff_summary = None
        if failures:
            diff_summary = self.diff_analyzer.format_diff(
                expected_status=expected.status_code,
                actual_status=response.status_code,
                expected_error_code=expected.expected_error_code,
                actual_error_code=actual_error_code,
                expected_field=expected.expected_error_field,
                actual_fields=actual_field_paths,
                missing_keys=missing_keys,
            )

        return test_status, failures, outcomes, diff_summary
