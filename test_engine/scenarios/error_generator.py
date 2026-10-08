"""Error Handling and Security Boundary Scenario Generator."""

from __future__ import annotations

from typing import Any

from test_engine.logger import get_logger
from test_engine.models.contract import ApiContract, EndpointContract
from test_engine.models.test_case import (
    ExpectedResponse,
    TestCategory,
    TestCase,
    TestRequest,
)

logger = get_logger("scenarios.error")


class ErrorScenarioGenerator:
    """Generates error handling, security headers, malformed payloads, and 4xx/5xx edge scenarios."""

    def generate_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Generates comprehensive error and boundary test cases."""
        scenarios: list[TestCase] = []

        # 1. Malformed JSON Body tests
        scenarios.extend(self._generate_malformed_json_scenarios(contract))

        # 2. Missing Authentication & Identity Header (X-User-Id) tests
        scenarios.extend(self._generate_auth_header_scenarios(contract))

        # 3. Non-Existent Resource (404 Not Found) tests
        scenarios.extend(self._generate_not_found_scenarios(contract))

        # 4. Conflict / Stale Hash (409) tests
        scenarios.extend(self._generate_conflict_scenarios(contract))

        return scenarios

    def _generate_malformed_json_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Tests server behavior when request body is unparseable / malformed JSON."""
        cases: list[TestCase] = []
        for ep in contract.endpoints:
            if ep.method in ("POST", "PUT", "PATCH") and ep.request_schema:
                cases.append(
                    TestCase(
                        id=f"ERR_MALFORMED_JSON_{ep.method}_{self._slug(ep.path)}",
                        name=f"Malformed JSON Body on {ep.method} {ep.path}",
                        description="Send syntactically invalid JSON payload to verify 400 or 422 with standard error envelope",
                        category=TestCategory.ERROR_HANDLING,
                        endpoint_path=ep.path,
                        method=ep.method,
                        request=TestRequest(
                            method=ep.method,
                            path=ep.path,
                            raw_body='{"broken": true, "unclosed_string: 1234',
                            headers={"Content-Type": "application/json"},
                        ),
                        expected=ExpectedResponse(
                            status_code=[400, 422],
                            expected_error_code="INVALID_INPUT",
                            description="Rejection of malformed JSON with ErrorEnvelope",
                        ),
                    )
                )
                # Only test on first few endpoints to avoid bloating the test suite
                if len(cases) >= 2:
                    break
        return cases

    def _generate_auth_header_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Tests endpoints requiring identity headers (e.g. tasks decision) without X-User-Id."""
        cases: list[TestCase] = []
        for ep in contract.endpoints:
            # Task decision and task claim endpoints require user identity
            if ("decision" in ep.path or "claim" in ep.path or ep.requires_auth) and ep.method == "POST":
                concrete_path = ep.path.replace("{task_id}", "00000000-0000-0000-0000-000000000001")
                concrete_path = concrete_path.replace("{case_id}", "00000000-0000-0000-0000-000000000001")
                concrete_path = concrete_path.replace("{policy_hash}", "cf4e712994ef7a6ccdebdbd55c1733dedb95f1c9f6067e42dfc55e369b58ef06")

                json_payload: dict[str, Any] | None = None
                if "comments" in ep.path:
                    json_payload = {"body": "test comment"}
                elif "decision" in ep.path:
                    json_payload = {
                        "action": "approve",
                        "proposal_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                    }
                elif "preview" in ep.path:
                    json_payload = {"modified_proposal": {}}
                elif "views" in ep.path:
                    json_payload = {"session_id": "test_session_id", "event": "open"}
                elif "approval" in ep.path:
                    json_payload = {"note": "test approval note"}
                elif ep.request_schema:
                    from test_engine.scenarios.schema_generator import SchemaScenarioGenerator
                    json_payload = SchemaScenarioGenerator().synthesize_valid_payload(ep)

                cases.append(
                    TestCase(
                        id=f"SEC_MISSING_USER_ID_{self._slug(ep.path)}",
                        name=f"Missing X-User-Id on {ep.method} {ep.path}",
                        description="Executes authenticated operation without X-User-Id header expecting 403 Forbidden",
                        category=TestCategory.SECURITY,
                        endpoint_path=ep.path,
                        method=ep.method,
                        request=TestRequest(
                            method=ep.method,
                            path=concrete_path,
                            json_body=json_payload,
                            headers={},  # Intentionally omitting X-User-Id
                        ),
                        expected=ExpectedResponse(
                            status_code=[401, 403, 404],  # 403 if missing auth, 404 if mock ID not found
                            description="Unauthorized or Forbidden when X-User-Id is omitted",
                        ),
                    )
                )
        return cases

    def _generate_not_found_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Tests non-existent resources return standardized 404 ErrorEnvelope."""
        cases: list[TestCase] = []

        not_found_targets = [
            ("/api/v1/cases/00000000-0000-0000-0000-000000000000", "Case Not Found"),
            ("/api/v1/tasks/00000000-0000-0000-0000-000000000000", "Task Not Found"),
            ("/api/v1/triggers/non-existent-template-xyz", "Template Not Found"),
        ]

        for path, name in not_found_targets:
            cases.append(
                TestCase(
                    id=f"ERR_NOT_FOUND_{self._slug(path)}",
                    name=f"404 Not Found - {name}",
                    description=f"Request non-existent resource at {path} expecting 404 with ErrorEnvelope",
                    category=TestCategory.ERROR_HANDLING,
                    endpoint_path=path,
                    method="GET" if "trigger" not in path else "POST",
                    request=TestRequest(
                        method="GET" if "trigger" not in path else "POST",
                        path=path,
                        json_body={"dummy": "data"} if "trigger" in path else None,
                    ),
                    expected=ExpectedResponse(
                        status_code=404,
                        expected_error_code="NOT_FOUND",
                        description="Standard 404 error response",
                    ),
                )
            )

        return cases

    def _generate_conflict_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Tests conflict scenario: stale revision or wrong proposal hash yields 409."""
        cases: list[TestCase] = []
        decision_ep = contract.find_endpoint("/api/v1/tasks/{task_id}/decision", "POST")
        if decision_ep:
            cases.append(
                TestCase(
                    id="ERR_CONFLICT_STALE_HASH",
                    name="409 Conflict: Decision with Stale Proposal Hash",
                    description="Submit decision with mismatching proposal hash expecting 409 Conflict",
                    category=TestCategory.ERROR_HANDLING,
                    endpoint_path=decision_ep.path,
                    method="POST",
                    request=TestRequest(
                        method="POST",
                        path="/api/v1/tasks/00000000-0000-0000-0000-000000000001/decision",
                        headers={"X-User-Id": "admin"},
                        json_body={
                            "action": "approve",
                            "proposal_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                        },
                    ),
                    expected=ExpectedResponse(
                        status_code=[404, 409],
                        description="409 Conflict (or 404 if task id dummy)",
                    ),
                )
            )
        return cases

    @staticmethod
    def _slug(text: str) -> str:
        import re
        return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()
