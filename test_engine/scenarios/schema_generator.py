"""Generic Schema-Driven Scenario Generator."""

from __future__ import annotations

import copy
import re
from typing import Any

from test_engine.logger import get_logger
from test_engine.models.contract import EndpointContract, FieldValidationRule, ParameterSpec
from test_engine.models.test_case import (
    ExpectedResponse,
    TestCategory,
    TestCase,
    TestRequest,
)

logger = get_logger("scenarios.schema")


class SchemaScenarioGenerator:
    """Generates schema validation test cases (valid, missing fields, type violations, boundary values)."""

    def __init__(self, auth_user_id: str = "admin") -> None:
        self.auth_user_id = auth_user_id

    @classmethod
    def resolve_concrete_path(cls, path: str, parameters: list[ParameterSpec] | None = None) -> str:
        """Substitutes path parameters with syntactically valid sample values (e.g. valid UUIDs)."""
        def _replace_param(match: re.Match[str]) -> str:
            param_name = match.group(1)
            p_spec = next((p for p in (parameters or []) if p.name == param_name), None)
            schema = p_spec.schema_def if p_spec else {}
            p_format = schema.get("format", "").lower()
            p_type = schema.get("type", "").lower()

            if (
                p_format == "uuid"
                or "uuid" in param_name.lower()
                or param_name.lower().endswith("_id")
                or param_name.lower() == "id"
            ):
                return "00000000-0000-0000-0000-000000000001"
            if param_name.lower() in ("template", "workflow"):
                return "returned-ach"
            if param_name.lower() == "system":
                return "payment"
            if "hash" in param_name.lower():
                return "cf4e712994ef7a6ccdebdbd55c1733dedb95f1c9f6067e42dfc55e369b58ef06"
            if p_type in ("integer", "int"):
                return "1"
            return "sample-param-val"

        return re.sub(r"\{([A-Za-z0-9_]+)\}", _replace_param, path)

    def generate_scenarios(self, endpoint: EndpointContract) -> list[TestCase]:
        """Generates all generic schema-driven test cases for an endpoint."""
        scenarios: list[TestCase] = []

        if not endpoint.request_schema:
            return scenarios

        concrete_path = self.resolve_concrete_path(endpoint.path, endpoint.parameters)
        auth_headers = {"X-User-Id": self.auth_user_id}

        # 1. Synthesize baseline valid payload
        baseline_payload = self.synthesize_valid_payload(endpoint)
        if baseline_payload:
            valid_status = [200, 201, 404, 409] if "{" in endpoint.path else [200, 201]
            scenarios.append(
                TestCase(
                    id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_VALID",
                    name=f"Valid Schema Request - {endpoint.method} {endpoint.path}",
                    description="Submit fully conformant payload meeting all OpenAPI schema constraints",
                    category=TestCategory.SCHEMA,
                    endpoint_path=endpoint.path,
                    method=endpoint.method,
                    request=TestRequest(
                        method=endpoint.method,
                        path=concrete_path,
                        headers=auth_headers,
                        json_body=baseline_payload,
                    ),
                    expected=ExpectedResponse(
                        status_code=valid_status,
                        description="Accepted with HTTP 200/201 (or 404 if resource ID does not exist in DB)",
                    ),
                )
            )

        # 2. Missing required fields
        for rule in endpoint.field_rules:
            if rule.required and rule.field_name in baseline_payload:
                payload_missing = copy.deepcopy(baseline_payload)
                del payload_missing[rule.field_name]

                scenarios.append(
                    TestCase(
                        id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_MISSING_{rule.field_name.upper()}",
                        name=f"Missing Required Field '{rule.field_name}'",
                        description=f"Omits required field '{rule.field_name}' to verify 422 Unprocessable Entity",
                        category=TestCategory.SCHEMA,
                        endpoint_path=endpoint.path,
                        method=endpoint.method,
                        request=TestRequest(
                            method=endpoint.method,
                            path=concrete_path,
                            headers=auth_headers,
                            json_body=payload_missing,
                        ),
                        expected=ExpectedResponse(
                            status_code=422,
                            expected_error_field=rule.field_name,
                            description=f"Field error for missing '{rule.field_name}'",
                        ),
                    )
                )

        # 3. Invalid types
        for rule in endpoint.field_rules:
            if rule.field_name in baseline_payload:
                invalid_val = self._generate_invalid_type_value(rule.field_type)
                payload_invalid = copy.deepcopy(baseline_payload)
                payload_invalid[rule.field_name] = invalid_val

                scenarios.append(
                    TestCase(
                        id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_INVALID_TYPE_{rule.field_name.upper()}",
                        name=f"Invalid Type for Field '{rule.field_name}'",
                        description=f"Provides wrong data type ({type(invalid_val).__name__} instead of {rule.field_type}) for '{rule.field_name}'",
                        category=TestCategory.SCHEMA,
                        endpoint_path=endpoint.path,
                        method=endpoint.method,
                        request=TestRequest(
                            method=endpoint.method,
                            path=concrete_path,
                            headers=auth_headers,
                            json_body=payload_invalid,
                        ),
                        expected=ExpectedResponse(
                            status_code=422,
                            expected_error_field=rule.field_name,
                            description=f"Field error for invalid type on '{rule.field_name}'",
                        ),
                    )
                )

        # 4. Boundary & Constraint violations
        for rule in endpoint.field_rules:
            boundary_cases = self._generate_boundary_violations(rule, baseline_payload)
            for case_suffix, bad_payload, desc in boundary_cases:
                scenarios.append(
                    TestCase(
                        id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_BOUNDARY_{rule.field_name.upper()}_{case_suffix}",
                        name=f"Boundary Violation: {rule.field_name} ({case_suffix})",
                        description=desc,
                        category=TestCategory.SCHEMA,
                        endpoint_path=endpoint.path,
                        method=endpoint.method,
                        request=TestRequest(
                            method=endpoint.method,
                            path=concrete_path,
                            headers=auth_headers,
                            json_body=bad_payload,
                        ),
                        expected=ExpectedResponse(
                            status_code=422,
                            expected_error_field=rule.field_name,
                            description=f"Validation rejection for boundary violation on '{rule.field_name}'",
                        ),
                    )
                )

        # 5. Strict extra properties test (if additionalProperties: False)
        has_strict = any(r.is_strict_extra for r in endpoint.field_rules) or (
            isinstance(endpoint.request_schema, dict)
            and endpoint.request_schema.get("additionalProperties") is False
        )
        if has_strict and baseline_payload:
            payload_extra = copy.deepcopy(baseline_payload)
            payload_extra["__unexpected_strict_field__"] = "rejected_extra_val"

            scenarios.append(
                TestCase(
                    id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_STRICT_EXTRA_FIELD",
                    name=f"Strict Extra Field Rejection - {endpoint.method} {endpoint.path}",
                    description="Submit unexpected additional property to strict model expecting 422",
                    category=TestCategory.SCHEMA,
                    endpoint_path=endpoint.path,
                    method=endpoint.method,
                    request=TestRequest(
                        method=endpoint.method,
                        path=concrete_path,
                        headers=auth_headers,
                        json_body=payload_extra,
                    ),
                    expected=ExpectedResponse(
                        status_code=422,
                        description="Rejection of extra property under strict schema mode",
                    ),
                )
            )

        # 6. HTTP Method Not Allowed test
        wrong_method = "DELETE" if endpoint.method == "POST" else "POST"
        scenarios.append(
            TestCase(
                id=f"SCHEMA_{endpoint.method}_{self._slugify(endpoint.path)}_METHOD_NOT_ALLOWED",
                name=f"Invalid HTTP Method {wrong_method} on {endpoint.path}",
                description=f"Sends unsupported HTTP method {wrong_method} expecting 405 Method Not Allowed",
                category=TestCategory.SCHEMA,
                endpoint_path=endpoint.path,
                method=wrong_method,
                request=TestRequest(
                    method=wrong_method,
                    path=concrete_path,
                    headers=auth_headers,
                    json_body=None,
                ),
                expected=ExpectedResponse(
                    status_code=[404, 405],
                    description="Method Not Allowed (405) or Not Found (404)",
                ),
            )
        )

        return scenarios

    def synthesize_valid_payload(self, endpoint: EndpointContract) -> dict[str, Any]:
        """Synthesizes a schema-valid request body payload matching field rules."""
        if "decision" in endpoint.path.lower():
            return {
                "action": "approve",
                "proposal_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "note": "valid review note",
            }

        payload: dict[str, Any] = {}
        for rule in endpoint.field_rules:
            payload[rule.field_name] = self._synthesize_field_value(rule)
        return payload

    def _synthesize_field_value(self, rule: FieldValidationRule) -> Any:
        """Generates a conformant synthetic value for a given field rule."""
        if rule.enum_values:
            return rule.enum_values[0]

        name = rule.field_name.lower()
        ftype = rule.field_type.lower()

        # Specific known semantic fields
        if (
            getattr(rule, "format", None) == "uuid"
            or "uuid" in name
            or name in ("case_id", "task_id")
            or (name.endswith("_id") and name not in ("tenant_id", "user_id"))
        ):
            return "00000000-0000-0000-0000-000000000001"
        if "provider" in name:
            return "mock"
        if "proposal_hash" in name or ("hash" in name and "bundle" not in name):
            return "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        if name == "modified_proposal":
            return {}
        if name == "session_id":
            return "valid_session_id"
        if name == "event":
            return "open"
        if name == "note":
            return "valid review note"
        if "trace" in name:
            return "TRC-VALID-100234"
        if "reason_code" in name or "return_code" in name:
            return "R01"
        if "currency" in name:
            return "USD"
        if "date" in name:
            return "2026-09-15"
        if "tenant" in name:
            return "tenant_qa_01"
        if "account" in name:
            return "acct_test_8819"
        if "customer" in name:
            return "cust_test_4102"
        if "authorization" in name:
            return "auth_test_9921"

        if ftype in ("integer", "int"):
            min_val = int(rule.minimum) if rule.minimum is not None else 1000
            return max(min_val, 1000)
        elif ftype in ("number", "float"):
            min_val = float(rule.minimum) if rule.minimum is not None else 10.5
            return max(min_val, 10.5)
        elif ftype in ("boolean", "bool"):
            return True
        elif ftype == "array":
            return []
        elif ftype == "object":
            return {}

        # String default with pattern or length constraints
        if rule.pattern:
            if "r\\d{2}" in rule.pattern.lower():
                return "R01"
            if "[a-z0-9" in rule.pattern.lower():
                return "TRC-VALID-123456"

        min_len = rule.min_length or 1
        return f"valid_{rule.field_name[:10]}_{'x' * max(0, min_len - 6)}"

    def _generate_invalid_type_value(self, field_type: str) -> Any:
        """Returns a value guaranteed to fail validation for the given type."""
        ftype = field_type.lower()
        if ftype in ("integer", "int", "number", "float"):
            return "not-a-number-string"
        elif ftype in ("string", "str"):
            return 999999  # integer instead of string
        elif ftype in ("boolean", "bool"):
            return "not-a-boolean"
        elif ftype == "array":
            return "not-an-array"
        return ["unexpected", "array"]

    def _generate_boundary_violations(
        self, rule: FieldValidationRule, baseline: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any], str]]:
        """Produces boundary violation payloads for strings, numbers, and dates."""
        cases: list[tuple[str, dict[str, Any], str]] = []

        if rule.field_name not in baseline:
            return cases

        # Min length string violation
        if rule.min_length and rule.min_length > 0:
            payload = copy.deepcopy(baseline)
            payload[rule.field_name] = ""
            cases.append(
                (
                    "EMPTY_STRING",
                    payload,
                    f"Empty string for field '{rule.field_name}' requiring min length {rule.min_length}",
                )
            )

        # Max length violation
        if rule.max_length:
            payload = copy.deepcopy(baseline)
            payload[rule.field_name] = "A" * (rule.max_length + 10)
            cases.append(
                (
                    "EXCEEDS_MAX_LENGTH",
                    payload,
                    f"String exceeding max length ({rule.max_length}) for '{rule.field_name}'",
                )
            )

        # Pattern regex violation
        if rule.pattern:
            payload = copy.deepcopy(baseline)
            payload[rule.field_name] = "INVALID!!!REGEX###"
            cases.append(
                (
                    "REGEX_MISMATCH",
                    payload,
                    f"Value violating regex pattern '{rule.pattern}' for '{rule.field_name}'",
                )
            )

        # Minimum value violation for numeric fields
        if rule.minimum is not None:
            payload = copy.deepcopy(baseline)
            payload[rule.field_name] = rule.minimum - 1
            cases.append(
                (
                    "BELOW_MINIMUM",
                    payload,
                    f"Numeric value below minimum ({rule.minimum}) for '{rule.field_name}'",
                )
            )

        return cases

    @staticmethod
    def _slugify(text: str) -> str:
        """Converts endpoint path to a clean uppercase identifier."""
        return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
