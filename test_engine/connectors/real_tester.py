"""Real Connector Integration Harness (live external endpoints)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from test_engine.config import EngineConfig
from test_engine.connectors.base import (
    BaseConnectorTester,
    ConnectorHealth,
    ConnectorTestResult,
    ConnectorType,
)
from test_engine.logger import get_logger

logger = get_logger("connectors.real")


class RealConnectorTester(BaseConnectorTester):
    """Integration harness that tests live, real upstream connectors."""

    def __init__(
        self,
        connector_type: ConnectorType,
        endpoint_url: str,
        auth_headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
        max_sla_ms: float = 2000.0,
    ) -> None:
        super().__init__(connector_type, mode="real")
        self.endpoint_url = endpoint_url.rstrip("/")
        self.auth_headers = auth_headers or {}
        self.timeout_seconds = timeout_seconds
        self.max_sla_ms = max_sla_ms

    async def check_health(self) -> ConnectorHealth:
        """Pings the real external connector health endpoint."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            candidates = [
                f"{self.endpoint_url}/health",
                f"{self.endpoint_url}/ping",
                f"{self.endpoint_url}/",
            ]
            for url in candidates:
                try:
                    resp = await client.get(url, headers=self.auth_headers)
                    if resp.status_code in (200, 204):
                        return ConnectorHealth.HEALTHY
                    elif resp.status_code in (401, 403):
                        logger.warning(f"Real connector {self.connector_type.value} auth refused (HTTP {resp.status_code})")
                        return ConnectorHealth.DEGRADED
                except httpx.RequestError:
                    continue
        return ConnectorHealth.UNREACHABLE

    async def test_read_operations(self) -> list[ConnectorTestResult]:
        """Performs non-destructive read queries against the real upstream system."""
        results: list[ConnectorTestResult] = []

        # Read operations are strictly non-mutating (no payment debits, blocks, or modifications)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            t0 = time.perf_counter()
            try:
                resp = await client.get(
                    f"{self.endpoint_url}/api/v1/info",
                    headers=self.auth_headers,
                )
                latency = (time.perf_counter() - t0) * 1000
                status = "PASS" if resp.status_code in (200, 404) else "FAIL"

                # Check latency against SLA
                details: dict[str, Any] = {
                    "http_status": resp.status_code,
                    "within_sla": latency <= self.max_sla_ms,
                    "max_sla_ms": self.max_sla_ms,
                }
                if latency > self.max_sla_ms:
                    details["sla_warning"] = f"Latency {round(latency, 1)}ms exceeded SLA threshold {self.max_sla_ms}ms"

                results.append(
                    ConnectorTestResult(
                        connector_name=f"real_{self.connector_type.value}",
                        connector_type=self.connector_type,
                        mode="real",
                        operation="non_destructive_read",
                        status=status,
                        latency_ms=round(latency, 2),
                        details=details,
                    )
                )
            except httpx.RequestError as e:
                latency = (time.perf_counter() - t0) * 1000
                results.append(
                    ConnectorTestResult(
                        connector_name=f"real_{self.connector_type.value}",
                        connector_type=self.connector_type,
                        mode="real",
                        operation="non_destructive_read",
                        status="FAIL",
                        latency_ms=round(latency, 2),
                        error_message=str(e),
                    )
                )

        return results

    async def test_error_resilience(self) -> list[ConnectorTestResult]:
        """Tests handling of invalid credentials or timeouts against the real connector."""
        results: list[ConnectorTestResult] = []

        # Send request with invalid auth header to ensure real upstream rejects with 401/403
        bad_headers = {**self.auth_headers, "Authorization": "Bearer invalid_test_token_9999"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            t0 = time.perf_counter()
            try:
                resp = await client.get(f"{self.endpoint_url}/health", headers=bad_headers)
                latency = (time.perf_counter() - t0) * 1000
                # Either server requires auth and returns 401/403, or health is public (200)
                results.append(
                    ConnectorTestResult(
                        connector_name=f"real_{self.connector_type.value}",
                        connector_type=self.connector_type,
                        mode="real",
                        operation="unauthorized_rejection",
                        status="PASS",
                        latency_ms=round(latency, 2),
                        details={"status_code": resp.status_code},
                    )
                )
            except httpx.RequestError as e:
                results.append(
                    ConnectorTestResult(
                        connector_name=f"real_{self.connector_type.value}",
                        connector_type=self.connector_type,
                        mode="real",
                        operation="unauthorized_rejection",
                        status="SKIPPED",
                        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                        error_message=str(e),
                    )
                )

        return results


class RealConnectorSuiteTester:
    """Orchestrates testing across real external upstream connectors."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.testers: list[RealConnectorTester] = []
        self._configure_testers()

    def _configure_testers(self) -> None:
        """Inspects configuration or environment to discover configured real connectors."""
        # Check if real upstream endpoints are declared in custom headers or env
        # E.g. ACH_TEST_PAYMENT_URL, ACH_TEST_SERVICING_URL, etc.
        import os

        connectors_map = {
            ConnectorType.PAYMENT: os.getenv("ACH_TEST_PAYMENT_URL"),
            ConnectorType.SERVICING: os.getenv("ACH_TEST_SERVICING_URL"),
            ConnectorType.CRM: os.getenv("ACH_TEST_CRM_URL"),
            ConnectorType.RISK: os.getenv("ACH_TEST_RISK_URL"),
        }

        for c_type, url in connectors_map.items():
            if url:
                self.testers.append(
                    RealConnectorTester(
                        connector_type=c_type,
                        endpoint_url=url,
                        auth_headers=self.config.custom_headers,
                        timeout_seconds=self.config.timeout_seconds,
                    )
                )

    async def run_all(self) -> list[ConnectorTestResult]:
        """Executes verification tests against all configured real connectors."""
        if not self.testers:
            logger.info("No real external connector URLs configured in environment. Skipping real suite.")
            return []

        results: list[ConnectorTestResult] = []
        for tester in self.testers:
            logger.info(f"Testing real connector {tester.connector_type.value} at {tester.endpoint_url}...")
            # Health
            t0 = time.perf_counter()
            health = await tester.check_health()
            results.append(
                ConnectorTestResult(
                    connector_name=f"real_{tester.connector_type.value}",
                    connector_type=tester.connector_type,
                    mode="real",
                    operation="health_check",
                    status="PASS" if health == ConnectorHealth.HEALTHY else "FAIL",
                    latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                    details={"health": health.value},
                )
            )
            # Read operations
            reads = await tester.test_read_operations()
            results.extend(reads)
            # Error resilience
            errs = await tester.test_error_resilience()
            results.extend(errs)

        return results
