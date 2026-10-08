"""Unified Test Scenario Generator Coordinator."""

from __future__ import annotations

from test_engine.config import EngineConfig, TestSuite
from test_engine.logger import get_logger
from test_engine.models.contract import ApiContract
from test_engine.models.test_case import TestCategory, TestCase
from test_engine.scenarios.ach_domain_generator import AchDomainScenarioGenerator
from test_engine.scenarios.error_generator import ErrorScenarioGenerator
from test_engine.scenarios.schema_generator import SchemaScenarioGenerator

logger = get_logger("scenarios.generator")


class ScenarioGenerator:
    """Coordinates generation of test scenarios across schema, ACH domain, security, and error suites."""

    def __init__(
        self,
        schema_gen: SchemaScenarioGenerator | None = None,
        ach_gen: AchDomainScenarioGenerator | None = None,
        error_gen: ErrorScenarioGenerator | None = None,
    ) -> None:
        self.schema_gen = schema_gen or SchemaScenarioGenerator()
        self.ach_gen = ach_gen or AchDomainScenarioGenerator()
        self.error_gen = error_gen or ErrorScenarioGenerator()

    def generate_all(self, contract: ApiContract, config: EngineConfig) -> list[TestCase]:
        """Generates all applicable test cases filtered by the configured test suites."""
        all_cases: list[TestCase] = []
        enabled_suites = set(config.suites)
        run_all = "all" in enabled_suites or TestSuite.ALL.value in enabled_suites

        logger.info(f"Generating test scenarios for target (suites={enabled_suites})...")

        # 1. Generic Schema Scenarios
        if run_all or "schema" in enabled_suites or TestSuite.SCHEMA.value in enabled_suites:
            for endpoint in contract.endpoints:
                if endpoint.request_schema:
                    cases = self.schema_gen.generate_scenarios(endpoint)
                    all_cases.extend(cases)

        # 2. ACH Domain Scenarios (Reason codes, trace shapes, dates, deduplication, lifecycle)
        if (
            run_all
            or "ach_domain" in enabled_suites
            or TestSuite.ACH_DOMAIN.value in enabled_suites
            or "business_rules" in enabled_suites
        ):
            ach_cases = self.ach_gen.generate_scenarios(contract)
            all_cases.extend(ach_cases)

        # 3. Error Handling and Security Boundary Scenarios
        if (
            run_all
            or "security" in enabled_suites
            or TestSuite.SECURITY.value in enabled_suites
            or "error_handling" in enabled_suites
        ):
            error_cases = self.error_gen.generate_scenarios(contract)
            all_cases.extend(error_cases)

        # 4. Connector and Tool Scenarios
        if (
            run_all
            or "connectors" in enabled_suites
            or TestSuite.CONNECTORS.value in enabled_suites
        ):
            from test_engine.connectors.workflow_bridge import WorkflowConnectorBridge

            bridge = WorkflowConnectorBridge(config)
            conn_cases = bridge.generate_connector_test_cases(contract)
            all_cases.extend(conn_cases)

        # If health suite enabled and not single-endpoint mode, add health check scenario
        if (
            (run_all or "health" in enabled_suites or TestSuite.HEALTH.value in enabled_suites)
            and not contract.is_single_endpoint_mode
        ):
            from test_engine.models.test_case import ExpectedResponse, TestRequest

            all_cases.insert(
                0,
                TestCase(
                    id="HEALTH_CHECK_ROOT",
                    name="System Health & Availability",
                    description="Validate target API health endpoint responds HTTP 200 OK",
                    category=TestCategory.HEALTH,
                    endpoint_path=config.health_path,
                    method="GET",
                    request=TestRequest(method="GET", path=config.health_path),
                    expected=ExpectedResponse(
                        status_code=200,
                        expected_keys=["status"],
                        description="Target health reporting ok status",
                    ),
                ),
            )

        logger.info(f"Generated {len(all_cases)} total test scenarios across categories: "
                    f"{sorted({c.category.value for c in all_cases})}")
        return all_cases
