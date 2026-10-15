"""Deployment Gate Runner for Phase 4: Gate and Evidence.

Evaluates deployments against real-user journeys, verifies pre-flight health,
enforces non-zero exit code on red deploys, and packages client sign-off evidence.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from test_engine.journeys.driver_browser import BrowserDriver
from test_engine.journeys.models import JourneyResult, StepStatus
from test_engine.journeys.runner import JourneyRunner
from test_engine.logger import get_logger
from test_engine.reporting.client_packager import ClientEvidencePackager

logger = get_logger("gate.runner")
console = Console()


@dataclass
class GateExecutionSummary:
    """Summary metrics of a deployment gate run."""
    deploy_passed: bool
    exit_code: int
    preflight_ok: bool
    preflight_details: dict[str, Any]
    total_journeys: int
    passed_journeys: int
    failed_journeys: int
    journey_results: list[JourneyResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)
    red_deploy_report_path: Path | None = None
    client_package_dir: Path | None = None


class DeploymentGateRunner:
    """Automated post-deployment gate runner.
    
    Verifies service health, executes 100% of real-user evaluation journeys,
    strictly fails red deploys, and generates client sign-off artifacts.
    """

    def __init__(
        self,
        runtime_url: str = "http://localhost:8000",
        ui_url: str = "http://localhost:3000",
        output_dir: Path = Path("reports/gate"),
        headless: bool = True,
        fail_fast: bool = False,
        bundle_client_report: bool = True,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.runtime_url = runtime_url.rstrip("/")
        self.ui_url = ui_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.headless = headless
        self.fail_fast = fail_fast
        self.bundle_client_report = bundle_client_report
        self.timeout_seconds = timeout_seconds

        self.screenshot_dir = self.output_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def check_preflight_health(self) -> tuple[bool, dict[str, Any]]:
        """Verifies that target runtime API and Control Center UI are up and healthy."""
        logger.info("Running pre-flight health checks against %s and %s...", self.runtime_url, self.ui_url)
        details: dict[str, Any] = {
            "runtime_url": self.runtime_url,
            "ui_url": self.ui_url,
            "api_healthy": False,
            "ui_healthy": False,
            "healthy": False,
            "errors": [],
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            # 1. Check Runtime API Health
            health_endpoint = f"{self.runtime_url}/api/v1/health"
            try:
                resp = await client.get(health_endpoint)
                if resp.status_code == 200:
                    details["api_healthy"] = True
                    details["api_status_data"] = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                else:
                    details["errors"].append(f"Runtime API health returned HTTP {resp.status_code} (expected 200)")
            except Exception as e:  # noqa: BLE001
                details["errors"].append(f"Failed to connect to Runtime API at {health_endpoint}: {e}")

            # 2. Check UI Reachability
            try:
                ui_resp = await client.get(self.ui_url)
                if ui_resp.status_code == 200:
                    details["ui_healthy"] = True
                else:
                    details["errors"].append(f"Control Center UI returned HTTP {ui_resp.status_code} (expected 200)")
            except Exception as e:  # noqa: BLE001
                details["errors"].append(f"Failed to connect to Control Center UI at {self.ui_url}: {e}")

        details["healthy"] = details["api_healthy"] and details["ui_healthy"]
        return details["healthy"], details

    async def run_gate(self) -> GateExecutionSummary:
        """Executes the full deployment gate workflow."""
        start_time = time.monotonic()
        console.print(
            Panel(
                f"[bold cyan]Return ACH Deployment Gate - Phase 4[/bold cyan]\n"
                f"Target Runtime API: [green]{self.runtime_url}[/green]\n"
                f"Control Center UI: [green]{self.ui_url}[/green]\n"
                f"Artifact Output Dir: [yellow]{self.output_dir}[/yellow]",
                title="🚀 Deployment Gate Started",
                border_style="cyan",
            )
        )

        # 1. Preflight Health Verification
        is_healthy, preflight_info = await self.check_preflight_health()
        if not is_healthy:
            duration = time.monotonic() - start_time
            failure_reasons = [f"Preflight health check failed: {err}" for err in preflight_info.get("errors", [])]
            logger.error("Preflight check failed. Rejecting deploy: %s", failure_reasons)

            red_report = self._generate_red_deploy_report(
                reasons=failure_reasons,
                journey_results=[],
                preflight_info=preflight_info,
            )

            self._render_failure_console(failure_reasons, [])

            return GateExecutionSummary(
                deploy_passed=False,
                exit_code=1,
                preflight_ok=False,
                preflight_details=preflight_info,
                total_journeys=0,
                passed_journeys=0,
                failed_journeys=0,
                journey_results=[],
                duration_seconds=duration,
                failure_reasons=failure_reasons,
                red_deploy_report_path=red_report,
            )

        console.print("[bold green]✓ Pre-flight health checks passed.[/bold green]")

        # 2. Execute Real-User Journeys
        journey_runner = JourneyRunner(
            runtime_url=self.runtime_url,
            ui_url=self.ui_url,
            headless=self.headless,
            screenshot_dir=str(self.screenshot_dir),
        )

        journey_results: list[JourneyResult] = []
        journey_callables = [
            ("journey_1", journey_runner.run_journey_1),
            ("journey_2", journey_runner.run_journey_2),
            ("journey_3", journey_runner.run_journey_3),
            ("journey_4", journey_runner.run_journey_4),
            ("journey_5", journey_runner.run_journey_5),
            ("journey_6", journey_runner.run_journey_6),
            ("journey_7", journey_runner.run_journey_7),
            ("journey_8", journey_runner.run_journey_8),
        ]

        async with BrowserDriver(
            ui_url=self.ui_url,
            headless=self.headless,
            screenshot_dir=str(self.screenshot_dir),
        ) as browser:
            for j_id, func in journey_callables:
                logger.info("Gate executing %s...", j_id)
                try:
                    res = await func(browser)
                    journey_results.append(res)
                    if not res.passed and self.fail_fast:
                        logger.warning("Fail-fast enabled: aborting gate on failure of %s", j_id)
                        break
                except Exception as e:
                    logger.exception("Unexpected exception in %s", j_id)
                    err_res = JourneyResult(
                        journey_id=j_id,
                        name=f"Execution of {j_id}",
                        scenario="unexpected-exception",
                        passed=False,
                        plain_english_summary=f"Journey encountered unhandled error: {e}",
                    )
                    journey_results.append(err_res)
                    if self.fail_fast:
                        break

        duration = time.monotonic() - start_time
        total_journeys = len(journey_results)
        passed_journeys = sum(1 for r in journey_results if r.passed)
        failed_journeys = total_journeys - passed_journeys
        all_passed = (total_journeys == 8) and (failed_journeys == 0)

        # 3. Evaluate Pass/Fail & Package Reports
        failure_reasons: list[str] = []
        red_report_path: Path | None = None
        client_pkg_dir: Path | None = None

        if not all_passed:
            if total_journeys < 8:
                failure_reasons.append(f"Incomplete evaluation: only {total_journeys}/8 journeys executed.")
            for r in journey_results:
                if not r.passed:
                    failed_steps = [s for s in r.steps if s.status == StepStatus.FAIL]
                    step_details = "; ".join(f"[{s.step_id}] {s.title} (expected: {s.expected}, actual: {s.actual})" for s in failed_steps)
                    failure_reasons.append(f"{r.journey_id} ({r.name}) FAILED: {step_details or r.plain_english_summary}")

            red_report_path = self._generate_red_deploy_report(
                reasons=failure_reasons,
                journey_results=journey_results,
                preflight_info=preflight_info,
            )
            self._render_failure_console(failure_reasons, journey_results)

        if self.bundle_client_report:
            pkg = ClientEvidencePackager.package(
                output_dir=self.output_dir,
                journey_results=journey_results,
                preflight_info=preflight_info,
                runtime_url=self.runtime_url,
                ui_url=self.ui_url,
                is_deploy_passed=all_passed,
            )
            client_pkg_dir = pkg.get("package_dir")

        if all_passed:
            self._render_success_console(journey_results, duration, client_pkg_dir)
            return GateExecutionSummary(
                deploy_passed=True,
                exit_code=0,
                preflight_ok=True,
                preflight_details=preflight_info,
                total_journeys=total_journeys,
                passed_journeys=passed_journeys,
                failed_journeys=0,
                journey_results=journey_results,
                duration_seconds=duration,
                failure_reasons=[],
                client_package_dir=client_pkg_dir,
            )
        else:
            return GateExecutionSummary(
                deploy_passed=False,
                exit_code=1,
                preflight_ok=True,
                preflight_details=preflight_info,
                total_journeys=total_journeys,
                passed_journeys=passed_journeys,
                failed_journeys=failed_journeys,
                journey_results=journey_results,
                duration_seconds=duration,
                failure_reasons=failure_reasons,
                red_deploy_report_path=red_report_path,
                client_package_dir=client_pkg_dir,
            )

    def _generate_red_deploy_report(
        self,
        reasons: list[str],
        journey_results: list[JourneyResult],
        preflight_info: dict[str, Any],
    ) -> Path:
        """Writes diagnostic red-deploy failure reports in JSON and Markdown formats."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report_data = {
            "deployment_verdict": "REJECTED_RED_DEPLOY",
            "timestamp": datetime.now(UTC).isoformat(),
            "target_runtime": self.runtime_url,
            "target_ui": self.ui_url,
            "failure_reasons": reasons,
            "preflight": preflight_info,
            "failed_journeys": [
                {
                    "journey_id": r.journey_id,
                    "name": r.name,
                    "summary": r.plain_english_summary,
                    "failed_steps": [
                        {
                            "step_id": s.step_id,
                            "title": s.title,
                            "actor": s.persona,
                            "expected": s.expected,
                            "actual": s.actual,
                            "screenshot": s.screenshot_path,
                        }
                        for s in r.steps
                        if s.status == StepStatus.FAIL
                    ],
                }
                for r in journey_results
                if not r.passed
            ],
            "actionable_remediation": [
                "Inspect the failed step details above and review the linked screenshot.",
                "Verify whether the regression was caused by policy engine logic or UI element rendering.",
                "Do NOT bypass the gate; fix the root cause and re-trigger deployment verification.",
            ],
        }

        json_file = self.output_dir / "red_deploy_failure.json"
        with json_file.open("w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        md_file = self.output_dir / "red_deploy_failure.md"
        md_lines = [
            "# 🚨 RED DEPLOYMENT REJECTED",
            "",
            "**Gate Verdict:** REJECTED  ",
            f"**Timestamp:** {report_data['timestamp']}  ",
            f"**Runtime API:** `{self.runtime_url}`  ",
            f"**Control Center UI:** `{self.ui_url}`  ",
            "",
            "## Failure Diagnostics",
            "",
        ]
        for reason in reasons:
            md_lines.append(f"- ❌ {reason}")

        md_lines.extend([
            "",
            "## Remediation Actions",
            "",
            "1. Inspect the failed step details and examine the generated screenshots in `reports/gate/screenshots/`.",
            "2. Confirm backend database connectivity and ensure mock/live connectors are running.",
            "3. Resolve identified defects and re-run deployment gate verification (`ach-test gate`).",
            "",
        ])

        with md_file.open("w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        logger.info("Red deploy failure diagnostics saved to %s and %s", json_file, md_file)
        return json_file

    def _render_success_console(
        self,
        results: list[JourneyResult],
        duration: float,
        client_pkg_dir: Path | None,
    ) -> None:
        """Renders green deployment pass banner to console."""
        table = Table(title="Deployment Gate: 100% Real-User Journey Pass", show_lines=False)
        table.add_column("Status", width=8, justify="center")
        table.add_column("Journey", style="cyan", width=12)
        table.add_column("Scenario Name", style="magenta", width=36)
        table.add_column("Time", justify="right", width=9)
        table.add_column("Verdict", style="dim")

        for r in results:
            table.add_row(
                "[bold green]PASS[/bold green]",
                r.journey_id,
                r.name,
                f"{r.duration_seconds:.2f}s",
                r.plain_english_summary,
            )

        console.print(table)

        summary_text = (
            f"[bold green]DEPLOYMENT GATE: PASSED (GREEN DEPLOY)[/bold green]\n"
            f"All 8 real-user journeys passed in {duration:.2f}s.\n"
            f"NACHA rules and client requirements verified.\n"
        )
        if client_pkg_dir:
            summary_text += f"Client Evidence Package: [bold cyan]{client_pkg_dir}[/bold cyan]\n"
            summary_text += f"Interactive Report: [bold cyan]{client_pkg_dir / 'index.html'}[/bold cyan]"

        console.print(Panel(summary_text, title="Gate Sign-Off Verdict", border_style="green"))

    def _render_failure_console(
        self,
        reasons: list[str],
        results: list[JourneyResult],
    ) -> None:
        """Renders red deployment failure diagnostics banner to console."""
        failure_text = (
            "[bold red]DEPLOYMENT GATE: FAILED (RED DEPLOY REJECTED)[/bold red]\n"
            "The deployment failed one or more mandatory verification criteria:\n\n"
        )
        for r in reasons:
            failure_text += f" • [red]{r}[/red]\n"

        failure_text += (
            f"\nArtifacts: [yellow]{self.output_dir / 'red_deploy_failure.json'}[/yellow]\n"
            "Exiting with status code 1. Deployment pipeline must halt."
        )

        console.print(Panel(failure_text, title="🚨 Red Deploy Failure", border_style="red"))
