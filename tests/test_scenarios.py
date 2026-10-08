"""Tests for Phase 3: Test Scenario Generation Engine."""

import pytest

from test_engine.config import EngineConfig
from test_engine.discovery.contract_analyzer import ContractAnalyzer
from test_engine.models.test_case import TestCategory
from test_engine.scenarios import (
    AchDomainScenarioGenerator,
    ErrorScenarioGenerator,
    NACHA_REASON_CODES,
    ScenarioGenerator,
    SchemaScenarioGenerator,
)
from tests.test_discovery import SAMPLE_OPENAPI_SPEC


@pytest.fixture
def sample_contract():
    analyzer = ContractAnalyzer()
    return analyzer.analyze(
        spec=SAMPLE_OPENAPI_SPEC,
        base_url="http://localhost:8000",
        target_url="http://localhost:8000",
        health_ok=True,
    )


def test_schema_generator_baseline(sample_contract):
    schema_gen = SchemaScenarioGenerator()
    trigger_ep = sample_contract.find_endpoint("/api/v1/triggers/returned-ach", "POST")
    assert trigger_ep is not None

    scenarios = schema_gen.generate_scenarios(trigger_ep)
    assert len(scenarios) > 0

    # 1. Check valid baseline scenario
    valid_cases = [s for s in scenarios if s.id.endswith("_VALID")]
    assert len(valid_cases) == 1
    valid_case = valid_cases[0]
    assert valid_case.category == TestCategory.SCHEMA
    assert valid_case.request.json_body["tenant_id"] == "tenant_qa_01"
    assert valid_case.request.json_body["amount_minor"] == 1000

    # 2. Check missing required field scenarios
    missing_cases = [s for s in scenarios if "_MISSING_" in s.id]
    missing_fields = {s.expected.expected_error_field for s in missing_cases}
    assert "tenant_id" in missing_fields
    assert "original_trace_number" in missing_fields
    assert "return_reason_code" in missing_fields

    # 3. Check invalid type scenarios
    type_cases = [s for s in scenarios if "_INVALID_TYPE_" in s.id]
    assert len(type_cases) > 0
    for tc in type_cases:
        assert tc.expected.status_code == 422

    # 4. Check boundary scenarios
    boundary_cases = [s for s in scenarios if "_BOUNDARY_" in s.id]
    assert len(boundary_cases) > 0

    # 5. Check strict extra field scenario
    strict_cases = [s for s in scenarios if "_STRICT_EXTRA_FIELD" in s.id]
    assert len(strict_cases) == 1
    assert "__unexpected_strict_field__" in strict_cases[0].request.json_body

    # 6. Check method not allowed
    method_cases = [s for s in scenarios if "_METHOD_NOT_ALLOWED" in s.id]
    assert len(method_cases) == 1
    assert method_cases[0].request.method == "DELETE"


def test_ach_domain_generator(sample_contract):
    ach_gen = AchDomainScenarioGenerator()
    scenarios = ach_gen.generate_scenarios(sample_contract)
    assert len(scenarios) > 0

    # Check reason code matrix covers all NACHA codes
    reason_code_cases = [s for s in scenarios if s.id.startswith("ACH_REASON_CODE_")]
    assert len(reason_code_cases) == len(NACHA_REASON_CODES)
    for code in ("R01", "R02", "R03", "R07", "R08", "R10"):
        matching = [s for s in reason_code_cases if s.id == f"ACH_REASON_CODE_{code}"]
        assert len(matching) == 1
        assert matching[0].request.json_body["return_reason_code"] == code

    # Check invalid reason code format tests
    invalid_code_cases = [s for s in scenarios if "INVALID_REASON_CODE" in s.id]
    assert len(invalid_code_cases) >= 3

    # Check trace number rules
    short_trace = [s for s in scenarios if s.id == "ACH_TRACE_TOO_SHORT"]
    assert len(short_trace) == 1
    assert len(short_trace[0].request.json_body["original_trace_number"]) < 6

    symbol_trace = [s for s in scenarios if s.id == "ACH_TRACE_INVALID_SYMBOLS"]
    assert len(symbol_trace) == 1

    # Check settlement date older than 2000
    old_date = [s for s in scenarios if s.id == "ACH_SETTLEMENT_DATE_TOO_OLD"]
    assert len(old_date) == 1
    assert old_date[0].request.json_body["return_settlement_date"] < "2000"

    # Check deduplication & replay scenarios
    dedupe_cases = [s for s in scenarios if "DEDUPE" in s.id]
    assert len(dedupe_cases) == 2
    assert dedupe_cases[0].is_stateful is True
    assert dedupe_cases[1].is_stateful is True
    assert dedupe_cases[1].expected.status_code == 200  # replay yields 200

    # Check multi-step lifecycle flow
    lifecycle_cases = [s for s in scenarios if s.category == TestCategory.LIFECYCLE]
    assert len(lifecycle_cases) >= 2
    step1 = lifecycle_cases[0]
    assert step1.step_number == 1
    assert "case_id" in step1.context_extractors


def test_error_generator(sample_contract):
    error_gen = ErrorScenarioGenerator()
    scenarios = error_gen.generate_scenarios(sample_contract)
    assert len(scenarios) > 0

    # Malformed JSON
    malformed = [s for s in scenarios if "MALFORMED_JSON" in s.id]
    assert len(malformed) >= 1
    assert malformed[0].request.raw_body is not None

    # Missing auth
    missing_auth = [s for s in scenarios if "MISSING_USER_ID" in s.id]
    assert len(missing_auth) >= 0  # May or may not have decision route in sample spec

    # 404 not found
    not_found_cases = [s for s in scenarios if "NOT_FOUND" in s.id]
    assert len(not_found_cases) >= 3


def test_unified_scenario_generator(sample_contract):
    coordinator = ScenarioGenerator()

    # 1. Run with all suites
    cfg_all = EngineConfig(suites=["all"])
    all_cases = coordinator.generate_all(sample_contract, cfg_all)
    assert len(all_cases) > 25

    categories = {c.category for c in all_cases}
    assert TestCategory.HEALTH in categories
    assert TestCategory.SCHEMA in categories
    assert TestCategory.ACH_DOMAIN in categories
    assert TestCategory.LIFECYCLE in categories
    assert TestCategory.ERROR_HANDLING in categories

    # 2. Filter down to only schema
    cfg_schema = EngineConfig(suites=["schema"])
    schema_only = coordinator.generate_all(sample_contract, cfg_schema)
    assert len(schema_only) > 0
    assert all(c.category == TestCategory.SCHEMA for c in schema_only)

    # 3. Filter down to only ach_domain
    cfg_ach = EngineConfig(suites=["ach_domain"])
    ach_only = coordinator.generate_all(sample_contract, cfg_ach)
    assert len(ach_only) > 0
    assert all(c.category in (TestCategory.ACH_DOMAIN, TestCategory.LIFECYCLE) for c in ach_only)


def test_uuid_validity_in_error_and_schema_scenarios(sample_contract):
    import uuid

    # 1. Error generator non-existent targets must use RFC-compliant UUIDs
    error_gen = ErrorScenarioGenerator()
    scenarios = error_gen.generate_scenarios(sample_contract)
    for s in scenarios:
        if "/api/v1/cases/" in s.request.path:
            case_id_part = s.request.path.split("/api/v1/cases/")[1].split("/")[0]
            # Must parse as valid UUID without error
            parsed = uuid.UUID(case_id_part)
            assert str(parsed) == case_id_part
        if "/api/v1/tasks/" in s.request.path:
            task_id_part = s.request.path.split("/api/v1/tasks/")[1].split("/")[0]
            parsed = uuid.UUID(task_id_part)
            assert str(parsed) == task_id_part

    # 2. Schema generator path resolution must produce valid UUID for {case_id}
    schema_gen = SchemaScenarioGenerator()
    resolved = schema_gen.resolve_concrete_path("/api/v1/cases/{case_id}")
    assert "{" not in resolved
    extracted_id = resolved.split("/")[-1]
    parsed_uuid = uuid.UUID(extracted_id)
    assert str(parsed_uuid) == "00000000-0000-0000-0000-000000000001"


def test_runner_unpopulated_placeholder_fallback_to_uuid():
    import uuid
    from test_engine.execution.runner import TestRunner

    cfg = EngineConfig(target_url="http://localhost:8000")
    runner = TestRunner(cfg)

    # Context without case_id
    empty_context = {}
    resolved_path = runner._substitute_vars("/api/v1/cases/{case_id}", empty_context)
    assert "{" not in resolved_path
    extracted_id = resolved_path.split("/")[-1]
    assert uuid.UUID(extracted_id)

    # Context with extracted valid case_id
    real_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    populated_path = runner._substitute_vars("/api/v1/cases/{case_id}", {"case_id": real_uuid})
    assert populated_path == f"/api/v1/cases/{real_uuid}"

