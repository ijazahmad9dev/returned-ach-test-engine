"""Domain-Specific Return ACH Scenario Generator."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
import uuid

from test_engine.logger import get_logger
from test_engine.models.contract import ApiContract, EndpointContract
from test_engine.models.test_case import (
    ExpectedResponse,
    TestCategory,
    TestCase,
    TestRequest,
)

logger = get_logger("scenarios.ach_domain")

# Standard NACHA Return Reason Codes and their business descriptions
NACHA_REASON_CODES: dict[str, str] = {
    "R01": "Insufficient Funds (NSF)",
    "R02": "Account Closed",
    "R03": "No Account / Unable to Locate Account",
    "R04": "Invalid Account Number Structure",
    "R07": "Authorization Revoked by Customer",
    "R08": "Payment Stopped",
    "R10": "Customer Advises Unauthorized / Not Authorized",
    "R16": "Account Frozen / Legal Block",
    "R20": "Non-Transaction Account",
}


class AchDomainScenarioGenerator:
    """Generates financial ACH domain test scenarios including reason codes, trace rules, and lifecycles."""

    def __init__(self, tenant_id: str = "tenant_qa_01", default_user_id: str = "admin") -> None:
        self.tenant_id = tenant_id
        self.default_user_id = default_user_id

    def _get_trigger_path(self, trigger_ep: EndpointContract) -> str:
        """Returns concrete path for trigger endpoint replacing template placeholders."""
        path = trigger_ep.path
        path = path.replace("{template}", "returned-ach")
        path = path.replace("{workflow}", "returned-ach")
        return path

    def generate_scenarios(self, contract: ApiContract) -> list[TestCase]:
        """Generates domain test cases based on discovered endpoints and contracts."""
        scenarios: list[TestCase] = []

        # Find trigger endpoint: e.g. /api/v1/triggers/returned-ach or any trigger endpoint
        trigger_ep = self._find_trigger_endpoint(contract)
        if not trigger_ep:
            return scenarios

        # 1. NACHA Return Reason Codes Matrix
        scenarios.extend(self._generate_reason_code_matrix(trigger_ep))

        # 2. Reason code format violations
        scenarios.extend(self._generate_invalid_reason_codes(trigger_ep))

        # 3. Trace Number Format & Shape rules
        scenarios.extend(self._generate_trace_number_scenarios(trigger_ep))

        # 4. Settlement Date Business Logic
        scenarios.extend(self._generate_settlement_date_scenarios(trigger_ep))

        # 5. Deduplication & Replay Idempotency
        scenarios.extend(self._generate_deduplication_scenarios(trigger_ep))

        # 6. Multi-step Full Lifecycle Flow
        scenarios.extend(self._generate_lifecycle_flow(contract, trigger_ep))

        return scenarios

    def _find_trigger_endpoint(self, contract: ApiContract) -> EndpointContract | None:
        """Locates trigger endpoint in the API contract."""
        for ep in contract.endpoints:
            if "trigger" in ep.path.lower() and ep.method == "POST":
                return ep
        return None

    def _base_ach_payload(
        self,
        reason_code: str = "R01",
        trace_number: str | None = None,
        settlement_date: str | None = None,
        amount_minor: int = 15000,
        currency: str = "USD",
        scenario: str | None = None,
        account_ref: str = "ACC-0001",
        customer_ref: str = "CUS-0001",
        authorization_ref: str = "AUTH-0001",
    ) -> dict[str, Any]:
        """Constructs a standard Return ACH trigger payload conforming to Trigger contract with fresh dynamic data."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        actual_trace = trace_number or f"TRC-{reason_code}-{uuid.uuid4().hex[:8].upper()}"
        actual_date = settlement_date or today

        payload: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "source_event_id": f"evt_{actual_trace.lower()}",
            "original_trace_number": actual_trace,
            "return_reason_code": reason_code,
            "return_settlement_date": actual_date,
            "amount_minor": amount_minor,
            "currency": currency,
            "account_ref": account_ref,
            "customer_ref": customer_ref,
            "authorization_ref": authorization_ref,
        }
        if scenario:
            payload["scenario"] = scenario
        return payload

    def _generate_reason_code_matrix(self, trigger_ep: EndpointContract) -> list[TestCase]:
        """Tests each core NACHA return reason code with fresh trace references and exact 201 Created."""
        trigger_path = self._get_trigger_path(trigger_ep)
        cases: list[TestCase] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for code, description in NACHA_REASON_CODES.items():
            trace = f"TRC-{code}-{uuid.uuid4().hex[:8].upper()}"
            payload = self._base_ach_payload(
                reason_code=code,
                trace_number=trace,
                settlement_date=today,
            )
            cases.append(
                TestCase(
                    id=f"ACH_REASON_CODE_{code}",
                    name=f"ACH Return Reason Code {code} ({description})",
                    description=f"Validate processing of NACHA return code {code}: {description}",
                    category=TestCategory.ACH_DOMAIN,
                    endpoint_path=trigger_ep.path,
                    method="POST",
                    request=TestRequest(
                        method="POST",
                        path=trigger_path,
                        json_body=payload,
                    ),
                    expected=ExpectedResponse(
                        status_code=201,
                        expected_keys=["case_id", "created"],
                        description=f"Trigger accepted and created for {code}",
                    ),
                )
            )
        return cases

    def _generate_invalid_reason_codes(self, trigger_ep: EndpointContract) -> list[TestCase]:
        r"""Tests invalid format for return_reason_code (must match ^R\d{2}$)."""
        trigger_path = self._get_trigger_path(trigger_ep)
        invalid_codes = [
            ("R1", "Single digit reason code"),
            ("R100", "Three digit reason code"),
            ("INVALID", "Alphabetic non-code"),
            ("99R", "Reversed reason code format"),
        ]
        cases: list[TestCase] = []
        for bad_code, desc in invalid_codes:
            payload = self._base_ach_payload(reason_code=bad_code, trace_number="TRC-BAD-CODE-01")
            cases.append(
                TestCase(
                    id=f"ACH_INVALID_REASON_CODE_{bad_code.replace(' ', '_')}",
                    name=f"Invalid Reason Code Shape: {bad_code}",
                    description=f"Verifies rejection of malformed reason code: {desc}",
                    category=TestCategory.ACH_DOMAIN,
                    endpoint_path=trigger_ep.path,
                    method="POST",
                    request=TestRequest(
                        method="POST",
                        path=trigger_path,
                        json_body=payload,
                    ),
                    expected=ExpectedResponse(
                        status_code=422,
                        expected_error_field="return_reason_code",
                        description="422 Unprocessable Entity with return_reason_code validation error",
                    ),
                )
            )
        return cases

    def _generate_trace_number_scenarios(self, trigger_ep: EndpointContract) -> list[TestCase]:
        """Tests trace number shape: alphanumeric 6-64 characters."""
        trigger_path = self._get_trigger_path(trigger_ep)
        cases: list[TestCase] = []

        # Trace too short (< 6 chars)
        payload_short = self._base_ach_payload(trace_number="TRC1")
        cases.append(
            TestCase(
                id="ACH_TRACE_TOO_SHORT",
                name="Trace Number Below Minimum Length (4 < 6 chars)",
                description="original_trace_number below 6 alphanumeric chars must be rejected",
                category=TestCategory.ACH_DOMAIN,
                endpoint_path=trigger_ep.path,
                method="POST",
                request=TestRequest(method="POST", path=trigger_path, json_body=payload_short),
                expected=ExpectedResponse(
                    status_code=422,
                    expected_error_field="original_trace_number",
                    description="422 validation failure on trace length",
                ),
            )
        )

        # Trace with invalid characters (disallowed symbols)
        payload_symbols = self._base_ach_payload(trace_number="TRC@2026#INVALID!")
        cases.append(
            TestCase(
                id="ACH_TRACE_INVALID_SYMBOLS",
                name="Trace Number With Disallowed Symbols",
                description="original_trace_number containing symbols outside alphanumeric and hyphen rejected",
                category=TestCategory.ACH_DOMAIN,
                endpoint_path=trigger_ep.path,
                method="POST",
                request=TestRequest(method="POST", path=trigger_path, json_body=payload_symbols),
                expected=ExpectedResponse(
                    status_code=422,
                    expected_error_field="original_trace_number",
                    description="422 regex pattern failure on trace number",
                ),
            )
        )

        return cases

    def _generate_settlement_date_scenarios(self, trigger_ep: EndpointContract) -> list[TestCase]:
        """Tests settlement date rules (must not be implausibly old < year 2000)."""
        trigger_path = self._get_trigger_path(trigger_ep)
        cases: list[TestCase] = []

        # Implausibly old settlement date (< 2000)
        payload_old = self._base_ach_payload(
            trace_number="TRC-ANCIENT-DATE-01",
            settlement_date="1998-05-12",
        )
        cases.append(
            TestCase(
                id="ACH_SETTLEMENT_DATE_TOO_OLD",
                name="Implausibly Old Settlement Date (< 2000)",
                description="return_settlement_date before year 2000 triggers settlement_is_not_absurd validator",
                category=TestCategory.ACH_DOMAIN,
                endpoint_path=trigger_ep.path,
                method="POST",
                request=TestRequest(method="POST", path=trigger_path, json_body=payload_old),
                expected=ExpectedResponse(
                    status_code=422,
                    expected_error_field="return_settlement_date",
                    description="422 error rejecting date older than 2000",
                ),
            )
        )

        return cases

    def _generate_deduplication_scenarios(self, trigger_ep: EndpointContract) -> list[TestCase]:
        """Tests deduplication: identical trace+code+date yields HTTP 200 replay with created=False."""
        trigger_path = self._get_trigger_path(trigger_ep)
        dedupe_trace = f"TRC-DEDUPE-{uuid.uuid4().hex[:8].upper()}"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payload = self._base_ach_payload(
            reason_code="R01",
            trace_number=dedupe_trace,
            settlement_date=today,
        )

        cases: list[TestCase] = [
            TestCase(
                id="ACH_DEDUPE_INITIAL_TRIGGER",
                name="Deduplication: Initial Trigger Submission",
                description="First submission of event triggers case creation (HTTP 201 Created)",
                category=TestCategory.ACH_DOMAIN,
                endpoint_path=trigger_ep.path,
                method="POST",
                request=TestRequest(method="POST", path=trigger_path, json_body=payload),
                expected=ExpectedResponse(
                    status_code=201,
                    expected_keys=["case_id", "created"],
                    description="Initial creation accepted",
                ),
                is_stateful=True,
                step_number=1,
            ),
            TestCase(
                id="ACH_DEDUPE_REPLAY_TRIGGER",
                name="Deduplication: Duplicate Replay Submission",
                description="Duplicate submission of identical trace/reason/date returns HTTP 200 replay",
                category=TestCategory.ACH_DOMAIN,
                endpoint_path=trigger_ep.path,
                method="POST",
                request=TestRequest(method="POST", path=trigger_path, json_body=payload),
                expected=ExpectedResponse(
                    status_code=200,
                    expected_keys=["case_id", "created"],
                    description="Replay of existing case recognized (HTTP 200, created=false)",
                ),
                is_stateful=True,
                step_number=2,
                depends_on="ACH_DEDUPE_INITIAL_TRIGGER",
            ),
        ]
        return cases

    def _generate_lifecycle_flow(
        self, contract: ApiContract, trigger_ep: EndpointContract
    ) -> list[TestCase]:
        """Generates multi-step lifecycle flow: trigger -> inspect case -> inspect task -> handoff."""
        trigger_path = self._get_trigger_path(trigger_ep)
        cases_ep = contract.find_endpoint("/api/v1/cases/{case_id}", "GET")
        tasks_ep = contract.find_endpoint("/api/v1/tasks", "GET")

        # If case/task endpoints exist in contract, generate sequential lifecycle test
        flow_trace = f"TRC-FLOW-{uuid.uuid4().hex[:8].upper()}"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payload = self._base_ach_payload(reason_code="R01", trace_number=flow_trace, settlement_date=today)

        lifecycle_cases: list[TestCase] = []

        step1 = TestCase(
            id="ACH_LIFECYCLE_STEP1_TRIGGER",
            name="Lifecycle Step 1: Trigger Case Creation",
            description="Initiate Returned ACH workflow via trigger API",
            category=TestCategory.LIFECYCLE,
            endpoint_path=trigger_ep.path,
            method="POST",
            request=TestRequest(method="POST", path=trigger_path, json_body=payload),
            expected=ExpectedResponse(status_code=201, expected_keys=["case_id"]),
            is_stateful=True,
            step_number=1,
            context_extractors={"case_id": "case_id"},
        )
        lifecycle_cases.append(step1)

        if cases_ep:
            step2 = TestCase(
                id="ACH_LIFECYCLE_STEP2_CASE_STATE",
                name="Lifecycle Step 2: Verify Created Case State",
                description="Fetch case details using extracted case_id",
                category=TestCategory.LIFECYCLE,
                endpoint_path=cases_ep.path,
                method="GET",
                request=TestRequest(
                    method="GET",
                    path="/api/v1/cases/{case_id}",
                    headers={"X-User-Id": self.default_user_id},
                ),
                expected=ExpectedResponse(status_code=200, expected_keys=["id", "state"]),
                is_stateful=True,
                step_number=2,
                depends_on="ACH_LIFECYCLE_STEP1_TRIGGER",
            )
            lifecycle_cases.append(step2)

        if tasks_ep:
            step3 = TestCase(
                id="ACH_LIFECYCLE_STEP3_QUERY_TASKS",
                name="Lifecycle Step 3: Query Review Tasks for Case",
                description="Query review tasks generated by workflow",
                category=TestCategory.LIFECYCLE,
                endpoint_path=tasks_ep.path,
                method="GET",
                request=TestRequest(
                    method="GET",
                    path="/api/v1/tasks",
                    params={"case_id": "{case_id}"},
                    headers={"X-User-Id": self.default_user_id},
                ),
                expected=ExpectedResponse(status_code=200),
                is_stateful=True,
                step_number=3,
                depends_on="ACH_LIFECYCLE_STEP1_TRIGGER",
            )
            lifecycle_cases.append(step3)

        return lifecycle_cases
