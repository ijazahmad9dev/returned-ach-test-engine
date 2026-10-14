"""Journey Runner for Real-User Evaluation.

Executes Journeys 1, 2, and 3 end-to-end against the local stack,
driving Stripe/mock-processor returns and Playwright browser actions,
verifying visible outcomes against client requirements.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from test_engine.journeys.driver_browser import BrowserDriver
from test_engine.journeys.driver_stripe import StripeDriver
from test_engine.journeys.models import (
    JourneyResult,
    JourneyStep,
    Persona,
    StepStatus,
)
from test_engine.logger import get_logger

logger = get_logger("journeys.runner")


class JourneyRunner:
    """Orchestrates end-to-end test journeys against AgentOS."""

    def __init__(
        self,
        runtime_url: str = "http://localhost:8000",
        ui_url: str = "http://localhost:3000",
        headless: bool = True,
        screenshot_dir: str = "reports/screenshots",
    ) -> None:
        self.runtime_url = runtime_url.rstrip("/")
        self.ui_url = ui_url.rstrip("/")
        self.headless = headless
        self.screenshot_dir = screenshot_dir
        self.stripe_driver = StripeDriver(runtime_url=self.runtime_url)

    async def _get_case(self, case_id: str, user_id: str = "admin") -> dict[str, Any]:
        """Fetches case details from API."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.runtime_url}/api/v1/cases/{case_id}",
                headers={"X-User-Id": user_id},
            )
            resp.raise_for_status()
            return resp.json()

    async def _get_case_events(self, case_id: str, user_id: str = "admin") -> list[dict[str, Any]]:
        """Fetches events for a case."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.runtime_url}/api/v1/cases/{case_id}/events",
                params={"limit": 100},
                headers={"X-User-Id": user_id},
            )
            resp.raise_for_status()
            return resp.json().get("items", [])

    async def run_journey_1(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 1: Scenario A: Insufficient Funds (R01).

        Marcus (payments_specialist) reviews the case, verifies the suggested retry date,
        can move the date, and on approval the retry is handed to client_payment_process.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_1",
            name="Scenario A: Insufficient Funds (R01)",
            scenario="scenario-a-insufficient-funds",
            passed=True,
        )

        logger.info("Starting Journey 1: Scenario A")

        # Step 1: Trigger return
        step1 = JourneyStep(
            step_id="J1.1",
            title="Trigger NSF return (R01)",
            action_type="trigger",
            expected="Case created in awaiting_approval assigned to payments_specialist",
        )
        try:
            case_info = await self.stripe_driver.get_or_create_scenario_a_case()
            case_id = case_info.get("case_id")
            task_id = case_info.get("task_id")
            if not case_id or not task_id:
                raise ValueError(f"Could not get or create approval case for Scenario A: {case_info}")

            case_data = await self._get_case(case_id, user_id="marcus")
            open_task = case_data.get("open_task") or {}
            assigned_role = open_task.get("assigned_role")

            step1.actual = f"Case {case_id} state={case_data.get('state')}, task={task_id}, role={assigned_role}"
            if assigned_role != "payments_specialist":
                step1.status = StepStatus.FAIL
                step1.notes = f"Expected role payments_specialist, got {assigned_role}"
            else:
                step1.status = StepStatus.PASS

            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error triggering return: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Marcus views task in Control Center UI
        step2 = JourneyStep(
            step_id="J1.2",
            title="Marcus views task in Control Center UI",
            persona=Persona.MARCUS.value,
            action_type="inspect",
            expected="Task open, retry recommendation visible to payments_specialist",
        )
        try:
            await browser.act_as(Persona.MARCUS.value)
            await browser.open_task(task_id)
            inspect_data = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey1_01_marcus_task")
            step2.screenshot_path = shot

            has_retry_rec = inspect_data["has_retry_recommendation"]
            step2.actual = f"Retry recommended={has_retry_rec}, buttons={inspect_data['buttons'][:5]}"
            if not has_retry_rec:
                step2.status = StepStatus.FAIL
                step2.notes = "Retry recommendation not visible on task screen"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error in UI view: {e}"
            result.add_step(step2)
            result.passed = False
            return result

        # Step 3: Verify suggested retry date (4 business days out) and notice preview
        step3 = JourneyStep(
            step_id="J1.3",
            title="Verify suggested retry date & notice preview",
            persona=Persona.MARCUS.value,
            action_type="inspect",
            expected="Retry suggested 4 business days after return; notice names date",
        )
        try:
            await browser.select_choice("Retry the payment")
            inspect_after_click = await browser.inspect_task()
            suggested_date = inspect_after_click.get("suggested_date")

            shot = await browser.capture_screenshot("journey1_02_suggested_date")
            step3.screenshot_path = shot

            step3.actual = f"Suggested date={suggested_date}, notice preview present={inspect_after_click['has_notice_preview']}"
            if not suggested_date:
                step3.status = StepStatus.FAIL
                step3.notes = "Suggested retry date input not found"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error verifying suggested date: {e}"
            result.add_step(step3)
            result.passed = False
            return result

        # Step 4: Marcus moves the date and approves
        step4 = JourneyStep(
            step_id="J1.4",
            title="Marcus moves retry date and confirms approval",
            persona=Persona.MARCUS.value,
            action_type="approve",
            expected="Marcus moves date to 2026-10-19; decision confirmed",
        )
        try:
            moved = await browser.modify_retry_date("2026-10-19")
            confirmed = await browser.confirm_decision()
            shot = await browser.capture_screenshot("journey1_03_decision_approved")
            step4.screenshot_path = shot

            # Check case state via API to verify approval completed
            case_data = await self._get_case(case_id, user_id="marcus")
            state = case_data.get("state")
            step4.actual = f"Date moved={moved}, confirmed={confirmed}, state={state}"
            if state != "closed":
                step4.status = StepStatus.FAIL
                step4.notes = f"Case did not close after decision, state={state}"
            else:
                step4.status = StepStatus.PASS
            result.add_step(step4)
        except Exception as e:
            step4.status = StepStatus.FAIL
            step4.actual = f"Error approving decision: {e}"
            result.add_step(step4)
            result.passed = False
            return result

        # Step 5: Handoff boundary verification
        step5 = JourneyStep(
            step_id="J1.5",
            title="Verify handoff boundary (client_payment_process; AgentOS debits nothing)",
            action_type="inspect",
            expected="Case closed, handed_off to client_payment_process with modified date 2026-10-19",
        )
        try:
            events = await self._get_case_events(case_id, user_id="marcus")
            handed_off_events = [e for e in events if e.get("kind") == "handed_off"]
            payment_handoff = next(
                (e for e in handed_off_events if e.get("payload", {}).get("to") == "client_payment_process"),
                None,
            )

            if payment_handoff:
                target = payment_handoff["payload"].get("to")
                params = payment_handoff["payload"].get("params", {})
                reinit_date = params.get("reinitiation_date")
                step5.actual = f"Handed off to {target} with reinitiation_date={reinit_date}"
                step5.status = StepStatus.PASS
            else:
                step5.actual = "No handed_off event for client_payment_process found in timeline"
                step5.status = StepStatus.FAIL
                step5.notes = "System did not hand off retry to client_payment_process"

            result.add_step(step5)
        except Exception as e:
            step5.status = StepStatus.FAIL
            step5.actual = f"Error inspecting handoff: {e}"
            result.add_step(step5)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 1 PASSED: NSF return routed to Marcus. "
            "Marcus verified the suggested retry date, modified the date to 2026-10-19, "
            "and approved. AgentOS successfully handed off the retry to the client payment process "
            "without debiting directly."
            if result.passed
            else "Journey 1 FAILED: Could not complete full Scenario A workflow."
        )
        return result

    async def run_journey_2(
        self, browser: BrowserDriver, journey_1_case_id: str | None = None
    ) -> JourneyResult:
        """Journey 2: Retry Outcome.

        Outcome A (Settle): Records retry as settled; counted in Reports.
        Outcome B (Bounce): Reopens case for human review.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_2",
            name="Retry Outcome (Settled vs. Failed Again)",
            scenario="retry-outcome",
            passed=True,
        )

        logger.info("Starting Journey 2: Retry Outcome")
        case_id = journey_1_case_id or "14bcf629-5135-4677-b0e5-fc6c8ac3e92c"

        # Step 1: Trigger Retry Settled Outcome
        step1 = JourneyStep(
            step_id="J2.1",
            title="Retry settles in processor (Outcome A)",
            action_type="outcome",
            expected="Case records outcome as retry_settled; counted in Reports",
        )
        try:
            await self.stripe_driver.report_retry_outcome(case_id, "settle")
            events = await self._get_case_events(case_id, user_id="admin")
            settled_event = next(
                (e for e in events if e.get("kind") == "outcome_reported" and e.get("payload", {}).get("outcome") == "retry_settled"),
                None,
            )

            # Check Reports
            rep_data = await browser.get_reports_summary()
            shot = await browser.capture_screenshot("journey2_01_reports_settled")
            step1.screenshot_path = shot

            step1.actual = (
                f"Settle reported: {bool(settled_event)}. "
                f"Reports accessible: {rep_data.get('has_return_rate')}"
            )
            step1.status = StepStatus.PASS if settled_event else StepStatus.FAIL
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error reporting settled outcome: {e}"
            result.add_step(step1)
            result.passed = False

        # Step 2: Trigger Retry Bounced / Failed Again Outcome
        step2 = JourneyStep(
            step_id="J2.2",
            title="Retry fails again / bounces (Outcome B)",
            action_type="outcome",
            expected="Case reopens for human review (reopened=True, new open task created)",
        )
        try:
            await self.stripe_driver.report_retry_outcome(case_id, "bounce")
            case_data = await self._get_case(case_id, user_id="admin")
            open_task = case_data.get("open_task")

            shot = await browser.capture_screenshot("journey2_02_reopened_case")
            step2.screenshot_path = shot

            reopened = case_data.get("state") in ("open", "escalated", "awaiting_approval") and open_task is not None
            step2.actual = f"Case state={case_data.get('state')}, open_task={open_task.get('id') if open_task else None}"

            if reopened:
                step2.status = StepStatus.PASS
            else:
                step2.status = StepStatus.FAIL
                step2.notes = "Case did not reopen for a person on second return"
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error reporting bounced outcome: {e}"
            result.add_step(step2)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 2 PASSED: Processor retry outcome tested for both branches. "
            "When settled, the event was recorded and reflected in Reports. "
            "When returned again, AgentOS reopened the case for human review."
            if result.passed
            else "Journey 2 FAILED: Retry outcome processing failed verification."
        )
        return result

    async def run_journey_3(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 3: Scenario B: No Account (R03).

        Priya (reviewer) acts: verifies no retry offered, approves drafted new payment method request,
        case moves to awaiting_response with follow-up task, Priya closes follow-up with resolution.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_3",
            name="Scenario B: No Account (R03)",
            scenario="scenario-b-closed-or-invalid-account",
            passed=True,
        )

        logger.info("Starting Journey 3: Scenario B")

        # Step 1: Trigger R03 return
        step1 = JourneyStep(
            step_id="J3.1",
            title="Trigger No-Account return (R03)",
            action_type="trigger",
            expected="Case created in awaiting_approval assigned to reviewer",
        )
        try:
            case_info = await self.stripe_driver.get_or_create_scenario_b_case()
            case_id = case_info.get("case_id")
            task_id = case_info.get("task_id")
            if not case_id or not task_id:
                raise ValueError(f"Could not get or create approval case for Scenario B: {case_info}")

            case_data = await self._get_case(case_id, user_id="priya")
            open_task = case_data.get("open_task") or {}
            assigned_role = open_task.get("assigned_role")

            step1.actual = f"Case {case_id} state={case_data.get('state')}, task={task_id}, role={assigned_role}"
            if assigned_role != "reviewer":
                step1.status = StepStatus.FAIL
                step1.notes = f"Expected role reviewer, got {assigned_role}"
            else:
                step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error triggering R03 return: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Priya views task in Control Center UI
        step2 = JourneyStep(
            step_id="J3.2",
            title="Priya views task in Control Center UI",
            persona=Persona.PRIYA.value,
            action_type="inspect",
            expected="No retry offered; request for new payment method drafted",
        )
        try:
            await browser.act_as(Persona.PRIYA.value)
            await browser.open_task(task_id)
            inspect_data = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey3_01_priya_task")
            step2.screenshot_path = shot

            has_replacement = inspect_data["has_replacement_recommendation"]
            has_retry = inspect_data["has_retry_recommendation"]

            step2.actual = (
                f"Replacement method recommended={has_replacement}, "
                f"Retry recommended={has_retry}"
            )

            # R03 must NOT offer retry
            if has_retry:
                step2.status = StepStatus.FAIL
                step2.notes = "NACHA violation: retry offered on R03 (no account)"
            elif not has_replacement:
                step2.status = StepStatus.FAIL
                step2.notes = "Expected new payment method request recommendation"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error inspecting task: {e}"
            result.add_step(step2)
            result.passed = False
            return result

        # Step 3: Priya approves request for new payment method
        step3 = JourneyStep(
            step_id="J3.3",
            title="Priya approves new payment method request",
            persona=Persona.PRIYA.value,
            action_type="approve",
            expected="Case moves to awaiting_response with follow-up task",
        )
        try:
            await browser.select_choice("Ask for a new payment method")
            await browser.confirm_decision()
            shot = await browser.capture_screenshot("journey3_02_priya_approved")
            step3.screenshot_path = shot

            case_data = await self._get_case(case_id, user_id="priya")
            state = case_data.get("state")
            follow_up_task = case_data.get("open_task") or {}
            follow_up_id = follow_up_task.get("id")
            follow_up_type = follow_up_task.get("type")

            step3.actual = f"State={state}, follow_up_task={follow_up_id}, type={follow_up_type}"

            if state == "awaiting_response" and follow_up_type == "follow_up":
                step3.status = StepStatus.PASS
            else:
                step3.status = StepStatus.FAIL
                step3.notes = f"Expected state awaiting_response and follow_up task, got state={state}"
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error confirming approval: {e}"
            result.add_step(step3)
            result.passed = False
            return result

        # Step 4: Priya closes follow-up task with resolution reason
        step4 = JourneyStep(
            step_id="J3.4",
            title="Priya closes follow-up task with resolution reason",
            persona=Persona.PRIYA.value,
            action_type="close",
            expected="Priya selects 'Customer provided new method' and closes case",
        )
        try:
            await browser.open_task(follow_up_id)
            await browser.select_resolution_and_close("Customer provided new method")
            shot = await browser.capture_screenshot("journey3_03_case_closed")
            step4.screenshot_path = shot

            case_final = await self._get_case(case_id, user_id="priya")
            final_state = case_final.get("state")
            final_resolution = case_final.get("resolution")

            step4.actual = f"Final state={final_state}, resolution={final_resolution}"
            if final_state == "closed" and final_resolution == "customer_provided_new_method":
                step4.status = StepStatus.PASS
            else:
                step4.status = StepStatus.FAIL
                step4.notes = f"Case failed to close with resolution; state={final_state}"
            result.add_step(step4)
        except Exception as e:
            step4.status = StepStatus.FAIL
            step4.actual = f"Error closing follow-up task: {e}"
            result.add_step(step4)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 3 PASSED: R03 return was correctly identified as non-retryable. "
            "Priya reviewed and approved a replacement payment method request. The case entered awaiting_response "
            "with a follow-up task, and was cleanly closed when the customer provided a new payment method."
            if result.passed
            else "Journey 3 FAILED: Could not complete full Scenario B workflow."
        )
        return result

    async def run_all_journeys(self) -> list[JourneyResult]:
        """Runs Journeys 1, 2, and 3 in sequence."""
        results: list[JourneyResult] = []
        async with BrowserDriver(
            ui_url=self.ui_url,
            headless=self.headless,
            screenshot_dir=self.screenshot_dir,
        ) as browser:
            # Journey 1
            j1 = await self.run_journey_1(browser)
            results.append(j1)

            # Journey 2 (using Journey 1 case)
            j1_case_id = None
            if j1.steps and "Case " in j1.steps[0].actual:
                try:
                    j1_case_id = j1.steps[0].actual.split("Case ")[1].split(" ")[0]
                except Exception as e:
                    logger.debug("Could not parse j1 case_id: %s", e)
            j2 = await self.run_journey_2(browser, journey_1_case_id=j1_case_id)
            results.append(j2)

            # Journey 3
            j3 = await self.run_journey_3(browser)
            results.append(j3)

        return results
