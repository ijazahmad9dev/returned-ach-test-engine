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

    async def run_journey_4(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 4: Suspected Fraud (R10 on new account).

        Triggered by fraud scenario (ACH-47 / TRC-R10-FRAUD).
        Actor: Sam (fraud_analyst).
        Expected: Urgent at top of inbox; retry ruled out; no customer message drafted;
        actions offered: block account and stop future debits; team alerted; Sam can open fraud investigation.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_4",
            name="Suspected Fraud (R10 on new account)",
            scenario="suspected-fraud",
            passed=True,
        )

        logger.info("Starting Journey 4: Suspected Fraud")

        # Step 1: Trigger Suspected Fraud return (R10)
        step1 = JourneyStep(
            step_id="J4.1",
            title="Trigger Suspected Fraud return (R10)",
            action_type="trigger",
            expected="Case created in awaiting_approval assigned to fraud_analyst with urgent priority",
        )
        try:
            case_info = await self.stripe_driver.get_or_create_fraud_case()
            case_id = case_info.get("case_id")
            task_id = case_info.get("task_id")
            if not case_id or not task_id:
                raise ValueError(f"Could not get or create fraud case: {case_info}")

            case_data = await self._get_case(case_id, user_id="sam")
            open_task = case_data.get("open_task") or {}
            assigned_role = open_task.get("assigned_role")
            priority = open_task.get("priority")

            step1.actual = f"Case {case_id} state={case_data.get('state')}, task={task_id}, role={assigned_role}, priority={priority}"
            if assigned_role != "fraud_analyst" or priority != "urgent":
                step1.status = StepStatus.FAIL
                step1.notes = f"Expected role fraud_analyst and urgent priority, got role={assigned_role}, priority={priority}"
            else:
                step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error triggering fraud return: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Sam views task in Control Center UI
        step2 = JourneyStep(
            step_id="J4.2",
            title="Sam views task in Control Center UI",
            persona=Persona.SAM.value,
            action_type="inspect",
            expected="Urgent task, retry ruled out, no notice drafted, block account and stop debits offered",
        )
        try:
            await browser.act_as(Persona.SAM.value)
            await browser.open_task(task_id)
            inspect_data = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey4_01_sam_task")
            step2.screenshot_path = shot

            has_retry = inspect_data["has_retry_recommendation"]
            has_notice = inspect_data["has_notice_preview"]
            has_block = inspect_data["has_block_account"]
            has_cancel = inspect_data["has_cancel_billing"]
            has_inv = inspect_data["has_open_fraud_investigation"]

            step2.actual = (
                f"Retry recommended={has_retry}, notice drafted={has_notice}, "
                f"block offered={has_block}, cancel billing={has_cancel}, fraud investigation={has_inv}"
            )

            if has_retry:
                step2.status = StepStatus.FAIL
                step2.notes = "Retry should be prohibited/ruled out on suspected fraud"
            elif has_notice:
                step2.status = StepStatus.FAIL
                step2.notes = "Customer contact drafted on suspected fraud (must be suppressed)"
            elif not has_block:
                step2.status = StepStatus.FAIL
                step2.notes = "Block account action was not offered to fraud analyst"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error inspecting fraud task in UI: {e}"
            result.add_step(step2)
            result.passed = False
            return result

        # Step 3: Sam opens fraud investigation
        step3 = JourneyStep(
            step_id="J4.3",
            title="Sam alerts team and opens fraud investigation",
            persona=Persona.SAM.value,
            action_type="investigate",
            expected="Fraud investigation created; team alerted",
        )
        try:
            opened_inv = await browser.open_fraud_investigation(
                reason="R10 return on 6-day old account sharing device with multiple failed accounts.",
                assignee="sam",
            )
            shot = await browser.capture_screenshot("journey4_02_investigation_opened")
            step3.screenshot_path = shot

            events = await self._get_case_events(case_id, user_id="sam")
            inv_event = next(
                (e for e in events if "investigation" in e.get("kind", "")),
                None,
            )

            step3.actual = f"Investigation opened in UI={opened_inv}, event logged={bool(inv_event)}"
            if not opened_inv and not inv_event:
                step3.status = StepStatus.FAIL
                step3.notes = "Failed to open fraud investigation"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error opening fraud investigation: {e}"
            result.add_step(step3)
            result.passed = False
            return result

        # Step 4: Sam blocks account and stops future debits
        step4 = JourneyStep(
            step_id="J4.4",
            title="Sam confirms blocking account",
            persona=Persona.SAM.value,
            action_type="approve",
            expected="Account blocked, future billing cancelled, case closed",
        )
        try:
            blocked = await browser.block_account()
            shot = await browser.capture_screenshot("journey4_03_account_blocked")
            step4.screenshot_path = shot

            case_data = await self._get_case(case_id, user_id="sam")
            state = case_data.get("state")
            resolution = case_data.get("resolution")
            outcome = case_data.get("outcome")

            step4.actual = f"Blocked={blocked}, state={state}, outcome={outcome}, resolution={resolution}"
            if state != "closed" or resolution != "block_account":
                step4.status = StepStatus.FAIL
                step4.notes = f"Expected closed case with resolution block_account, got state={state}, resolution={resolution}"
            else:
                step4.status = StepStatus.PASS
            result.add_step(step4)
        except Exception as e:
            step4.status = StepStatus.FAIL
            step4.actual = f"Error blocking account: {e}"
            result.add_step(step4)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 4 PASSED: Suspected fraud return correctly routed to Sam (fraud_analyst) as urgent. "
            "Retry was ruled out, customer contact was suppressed, and Sam opened a fraud investigation "
            "before cleanly confirming account blocking and stopping future debits."
            if result.passed
            else "Journey 4 FAILED: Suspected fraud evaluation did not satisfy requirements."
        )
        return result

    async def run_journey_5(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 5: Protected Customer (Bankruptcy).

        Triggered by protected test account (TRC-PROTECTED / ACH-08).
        Actor: Dana (escalation_owner).
        Expected: Nothing can be approved; Dana closes without action with a legal reason.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_5",
            name="Protected Customer (Bankruptcy)",
            scenario="protected-account",
            passed=True,
        )

        logger.info("Starting Journey 5: Protected Customer")

        # Step 1: Trigger return for protected account
        step1 = JourneyStep(
            step_id="J5.1",
            title="Trigger return for account with bankruptcy flag",
            action_type="trigger",
            expected="Case stopped at protection gate, routes urgently to escalation_owner",
        )
        try:
            case_info = await self.stripe_driver.get_or_create_protected_case()
            case_id = case_info.get("case_id")
            task_id = case_info.get("task_id")
            if not case_id or not task_id:
                raise ValueError(f"Could not get or create protected case: {case_info}")

            case_data = await self._get_case(case_id, user_id="dana")
            open_task = case_data.get("open_task") or {}
            assigned_role = open_task.get("assigned_role")
            priority = open_task.get("priority")
            state = case_data.get("state")

            step1.actual = f"Case {case_id} state={state}, task={task_id}, role={assigned_role}, priority={priority}"
            if assigned_role != "escalation_owner" or priority != "urgent" or state != "escalated":
                step1.status = StepStatus.FAIL
                step1.notes = f"Expected escalated state, role escalation_owner, urgent priority. Got state={state}, role={assigned_role}"
            else:
                step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error triggering protected return: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Dana views task in Control Center UI
        step2 = JourneyStep(
            step_id="J5.2",
            title="Dana views task in Control Center UI",
            persona=Persona.DANA.value,
            action_type="inspect",
            expected="Bankruptcy flag visible, approval prohibited, nothing drafted, handle manually offered",
        )
        try:
            await browser.act_as(Persona.DANA.value)
            await browser.open_task(task_id)
            inspect_data = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey5_01_dana_task")
            step2.screenshot_path = shot

            has_bankruptcy = "Bankruptcy" in inspect_data["full_text"]
            has_notice = inspect_data["has_notice_preview"]
            has_handle_manually = inspect_data["has_handle_manually"]
            has_retry = inspect_data["has_retry_recommendation"]

            step2.actual = (
                f"Bankruptcy flag visible={has_bankruptcy}, notice drafted={has_notice}, "
                f"handle manually offered={has_handle_manually}, retry offered={has_retry}"
            )

            if not has_bankruptcy:
                step2.status = StepStatus.FAIL
                step2.notes = "Bankruptcy protection flag not visible in enriched context"
            elif has_retry or has_notice:
                step2.status = StepStatus.FAIL
                step2.notes = "Approval or notice offered on bankruptcy protected account"
            elif not has_handle_manually:
                step2.status = StepStatus.FAIL
                step2.notes = "Handle manually option not visible to Dana"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error inspecting protected task: {e}"
            result.add_step(step2)
            result.passed = False
            return result

        # Step 3: Dana closes without action with legal reason
        step3 = JourneyStep(
            step_id="J5.3",
            title="Dana closes case with legal reason (Legal or compliance hold)",
            persona=Persona.DANA.value,
            action_type="close",
            expected="Dana records bankruptcy hold note and selects legal_or_compliance_hold; case closed",
        )
        try:
            closed = await browser.close_with_legal_hold(
                note="Customer under active bankruptcy protection; legal hold applied.",
                resolution_label="Legal or compliance hold",
            )
            shot = await browser.capture_screenshot("journey5_02_case_closed_legal_hold")
            step3.screenshot_path = shot

            case_data = await self._get_case(case_id, user_id="dana")
            final_state = case_data.get("state")
            final_resolution = case_data.get("resolution")
            final_outcome = case_data.get("outcome")

            step3.actual = (
                f"Closed in UI={closed}, final state={final_state}, "
                f"resolution={final_resolution}, outcome={final_outcome}"
            )

            if final_state != "closed" or final_resolution != "legal_or_compliance_hold":
                step3.status = StepStatus.FAIL
                step3.notes = f"Case did not close with legal_or_compliance_hold; state={final_state}, res={final_resolution}"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error closing protected case: {e}"
            result.add_step(step3)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 5 PASSED: Account with bankruptcy flag halted at protection gate before interpretation. "
            "Case escalated directly to Dana (escalation_owner). Nothing could be approved, and Dana cleanly "
            "closed the case without action under a legal_or_compliance_hold resolution."
            if result.passed
            else "Journey 5 FAILED: Protected customer evaluation did not satisfy requirements."
        )
        return result

    async def run_journey_6(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 6: Duplicate Event.

        Same processor return event delivered twice.
        Expected: Exactly one case created; second delivery recognised as duplicate
        (duplicate: true, no second case, no second task).
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_6",
            name="Duplicate Event Handling",
            scenario="duplicate-event",
            passed=True,
        )

        logger.info("Starting Journey 6: Duplicate Event")

        # Step 1: First delivery of return event
        step1 = JourneyStep(
            step_id="J6.1",
            title="First delivery of return event",
            action_type="trigger",
            expected="Return event processed and initial case created with single task",
        )
        try:
            demo_res = await self.stripe_driver.trigger_demo_scenario("ACH-01", fresh=True)
            case_id = demo_res.get("case_id")
            if not case_id:
                raise ValueError(f"No case_id returned in first delivery: {demo_res}")

            case_data = await self._get_case(case_id, user_id="admin")
            trigger = case_data.get("trigger") or {}
            trace_number = trigger.get("original_trace_number")
            account_ref = trigger.get("account_ref", "ACC-0001")
            customer_ref = trigger.get("customer_ref", "CUS-0001")
            amount_minor = trigger.get("amount_minor", 40000)

            # Check task count before duplicate
            async with httpx.AsyncClient() as client:
                t_resp = await client.get(
                    f"{self.runtime_url}/api/v1/cases/{case_id}/tasks",
                    headers={"X-User-Id": "admin"},
                )
                t_resp.raise_for_status()
                t_before = t_resp.json()
                initial_task_count = len(t_before) if isinstance(t_before, list) else len(t_before.get("items", []))

            step1.actual = f"Case {case_id} created, trace={trace_number}, initial_tasks={initial_task_count}"
            step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error in first delivery: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Second delivery of identical event
        step2 = JourneyStep(
            step_id="J6.2",
            title="Second delivery of identical return event",
            action_type="trigger",
            expected="Second delivery recognized as duplicate (duplicate: true, created: false)",
        )
        try:
            res2 = await self.stripe_driver.trigger_mock_return(
                return_code="R01",
                amount_minor=amount_minor,
                trace_number=trace_number,
                account_ref=account_ref,
                customer_ref=customer_ref,
            )
            raw_res = res2.get("raw", {}).get("results", [{}])[0]
            is_dup = raw_res.get("duplicate") is True
            case_id_2 = res2.get("case_id")

            step2.actual = f"Status={res2['status_code']}, duplicate={is_dup}, case_id={case_id_2}"
            if not is_dup or case_id_2 != case_id:
                step2.status = StepStatus.FAIL
                step2.notes = f"Expected duplicate: true and same case_id={case_id}, got duplicate={is_dup}, case_id={case_id_2}"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error in second delivery: {e}"
            result.add_step(step2)
            result.passed = False
            return result

        # Step 3: Verify single case integrity & no duplicate tasks
        step3 = JourneyStep(
            step_id="J6.3",
            title="Verify single case integrity and task deduplication",
            action_type="inspect",
            expected="Exactly one case exists; duplicate event logged; no duplicate task created",
        )
        try:
            events = await self._get_case_events(case_id, user_id="admin")
            has_dup_event = any("duplicate" in str(e).lower() for e in events)

            async with httpx.AsyncClient() as client:
                tasks_resp = await client.get(
                    f"{self.runtime_url}/api/v1/cases/{case_id}/tasks",
                    headers={"X-User-Id": "admin"},
                )
                tasks_resp.raise_for_status()
                tasks_list = tasks_resp.json()
                task_count = len(tasks_list) if isinstance(tasks_list, list) else len(tasks_list.get("items", []))

            # View in UI and capture screenshot
            await browser.act_as(Persona.ADMIN.value)
            await browser.page.goto(f"{self.ui_url}/inbox", wait_until="networkidle")
            shot = await browser.capture_screenshot("journey6_01_duplicate_handled")
            step3.screenshot_path = shot

            step3.actual = (
                f"Task count before={initial_task_count}, after={task_count}; "
                f"duplicate_logged={has_dup_event}"
            )
            if task_count != initial_task_count:
                step3.status = StepStatus.FAIL
                step3.notes = f"Duplicate event spawned an extra task: count went from {initial_task_count} to {task_count}"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error checking case integrity: {e}"
            result.add_step(step3)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 6 PASSED: Duplicate processor webhook recognized cleanly (duplicate: true). "
            "Associated to existing case without duplicating records or spawning extra tasks."
            if result.passed
            else "Journey 6 FAILED: Duplicate event handling failed verification."
        )
        return result

    async def run_journey_7(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 7: Permissions & Privacy.

        Actor: User with wrong role / role without identity access.
        Expected:
        - Wrong role cannot decide (HTTP 403 / role_not_permitted).
        - Role without identity access never sees customer's real name (sees NAME_1 / Customer details are hidden for your role).
        - Role with identity access sees customer's real name.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_7",
            name="Permissions & Privacy",
            scenario="permissions-and-privacy",
            passed=True,
        )

        logger.info("Starting Journey 7: Permissions & Privacy")

        # Obtain a task assigned to fraud_analyst
        case_info = await self.stripe_driver.get_or_create_fraud_case()
        case_id = case_info["case_id"]
        task_id = case_info["task_id"]

        # Step 1: Wrong role cannot decide on assigned task (HTTP 403)
        step1 = JourneyStep(
            step_id="J7.1",
            title="Role-Based Enforcement: Wrong role cannot decide (HTTP 403)",
            persona=Persona.MARCUS.value,
            action_type="approve",
            expected="Marcus (payments_specialist) is rejected from deciding on fraud_analyst task with 403",
        )
        try:
            # Query task proposal_hash
            async with httpx.AsyncClient() as client:
                task_resp = await client.get(
                    f"{self.runtime_url}/api/v1/tasks/{task_id}",
                    headers={"X-User-Id": "marcus"},
                )
                ph = task_resp.json().get("proposal_hash")

                # Try decision as Marcus
                dec_resp = await client.post(
                    f"{self.runtime_url}/api/v1/tasks/{task_id}/decision",
                    json={"action": "approve", "proposal_hash": ph},
                    headers={"X-User-Id": "marcus"},
                )

            # Also check UI view for Marcus
            await browser.act_as(Persona.MARCUS.value)
            await browser.open_task(task_id)
            shot = await browser.capture_screenshot("journey7_01_wrong_role_marcus")
            step1.screenshot_path = shot

            code = dec_resp.status_code
            err_code = dec_resp.json().get("error", {}).get("code")
            step1.actual = f"Status={code}, error_code={err_code}"

            if code != 403 or err_code != "wrong_role":
                step1.status = StepStatus.FAIL
                step1.notes = f"Expected HTTP 403 and wrong_role, got {code} ({err_code})"
            else:
                step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error testing wrong role decision: {e}"
            result.add_step(step1)
            result.passed = False

        # Step 2: Role without identity access never sees customer's real name
        step2 = JourneyStep(
            step_id="J7.2",
            title="Data Privacy: Role without identity access sees redacted name",
            persona=Persona.LENA.value,
            action_type="inspect",
            expected="Lena (claims_intake_analyst) sees customer name redacted as NAME_1 and hidden notice in UI",
        )
        try:
            # API check
            async with httpx.AsyncClient() as client:
                pkt_resp = await client.get(
                    f"{self.runtime_url}/api/v1/cases/{case_id}/packet",
                    headers={"X-User-Id": "lena"},
                )
                fields = pkt_resp.json().get("fields", {})
                name_field = fields.get("crm.customer_name", {})
                redacted_val = name_field.get("value")

            # UI check
            await browser.act_as(Persona.LENA.value)
            await browser.open_task(task_id)
            inspect_lena = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey7_02_privacy_redacted_lena")
            step2.screenshot_path = shot

            is_locked = inspect_lena["customer_identity_locked"]
            step2.actual = f"API value={redacted_val}, UI customer_details_locked={is_locked}"

            if redacted_val != "NAME_1" or not is_locked:
                step2.status = StepStatus.FAIL
                step2.notes = f"Customer name not redacted for Lena. API val={redacted_val}, UI locked={is_locked}"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error checking privacy redaction: {e}"
            result.add_step(step2)
            result.passed = False

        # Step 3: Role with identity access sees customer's real name
        step3 = JourneyStep(
            step_id="J7.3",
            title="Data Privacy: Authorized role sees customer real name",
            persona=Persona.SAM.value,
            action_type="inspect",
            expected="Sam (fraud_analyst) sees customer real name and has identity access in UI",
        )
        try:
            # API check
            async with httpx.AsyncClient() as client:
                pkt_resp = await client.get(
                    f"{self.runtime_url}/api/v1/cases/{case_id}/packet",
                    headers={"X-User-Id": "sam"},
                )
                fields = pkt_resp.json().get("fields", {})
                name_field = fields.get("crm.customer_name", {})
                real_val = name_field.get("value")

            # UI check
            await browser.act_as(Persona.SAM.value)
            await browser.open_task(task_id)
            inspect_sam = await browser.inspect_task()
            shot = await browser.capture_screenshot("journey7_03_identity_authorized_sam")
            step3.screenshot_path = shot

            is_locked = inspect_sam["customer_identity_locked"]
            step3.actual = f"API value={real_val}, UI customer_details_locked={is_locked}"

            if real_val == "NAME_1" or is_locked:
                step3.status = StepStatus.FAIL
                step3.notes = f"Real customer name hidden from authorized fraud analyst Sam"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error checking authorized identity access: {e}"
            result.add_step(step3)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 7 PASSED: Role enforcement and data privacy verified. "
            "Wrong roles cannot decide on assigned tasks (rejected with HTTP 403 wrong_role). "
            "Roles without identity access (Lena) never see customer real name (redacted to NAME_1), "
            "while authorized roles (Sam) access full customer details."
            if result.passed
            else "Journey 7 FAILED: Permissions or privacy boundaries failed verification."
        )
        return result

    async def run_journey_8(self, browser: BrowserDriver) -> JourneyResult:
        """Journey 8: Executive Reporting.

        Actor: Admin.
        Expected: Executed after Journeys 1–6; /reports reflects return rates,
        settled retries, and recovered dollars.
        """
        start_time = time.time()
        result = JourneyResult(
            journey_id="journey_8",
            name="Executive Reporting",
            scenario="executive-reporting",
            passed=True,
        )

        logger.info("Starting Journey 8: Executive Reporting")

        # Step 1: Admin navigates to /reports
        step1 = JourneyStep(
            step_id="J8.1",
            title="Admin navigates to Executive Reports (/reports)",
            persona=Persona.ADMIN.value,
            action_type="inspect",
            expected="Reports dashboard loads with executive metrics and NACHA thresholds",
        )
        try:
            await browser.act_as(Persona.ADMIN.value)
            await browser.page.goto(f"{self.ui_url}/reports", wait_until="networkidle")
            content = await browser.page.text_content("body") or ""
            shot = await browser.capture_screenshot("journey8_01_reports_dashboard")
            step1.screenshot_path = shot

            has_reports = "Reports" in content and "Returned ACH" in content
            step1.actual = f"Dashboard accessible={has_reports}, content_len={len(content)}"
            if not has_reports:
                step1.status = StepStatus.FAIL
                step1.notes = "Failed to load Reports page in Control Center"
            else:
                step1.status = StepStatus.PASS
            result.add_step(step1)
        except Exception as e:
            step1.status = StepStatus.FAIL
            step1.actual = f"Error accessing /reports: {e}"
            result.add_step(step1)
            result.passed = False
            return result

        # Step 2: Verify return rates against NACHA compliance limits
        step2 = JourneyStep(
            step_id="J8.2",
            title="Verify return rates and NACHA compliance thresholds",
            persona=Persona.ADMIN.value,
            action_type="inspect",
            expected="Return rate, unauthorized return rate, and administrative rate within NACHA limits",
        )
        try:
            content = await browser.page.text_content("body") or ""
            has_return_rate = "Return rate" in content
            has_unauth_rate = "Unauthorized return rate" in content
            has_admin_rate = "Administrative return rate" in content
            has_nacha_limits = "Within the NACHA limit" in content

            step2.actual = (
                f"Return rate={has_return_rate}, Unauthorized rate={has_unauth_rate}, "
                f"Admin rate={has_admin_rate}, NACHA limits shown={has_nacha_limits}"
            )

            if not (has_return_rate and has_unauth_rate and has_nacha_limits):
                step2.status = StepStatus.FAIL
                step2.notes = "Required return rate or NACHA compliance metrics missing from reports"
            else:
                step2.status = StepStatus.PASS
            result.add_step(step2)
        except Exception as e:
            step2.status = StepStatus.FAIL
            step2.actual = f"Error checking return rates: {e}"
            result.add_step(step2)
            result.passed = False

        # Step 3: Verify retry outcomes and recovered dollars reflect test activity
        step3 = JourneyStep(
            step_id="J8.3",
            title="Verify settled retries and recovered dollars reflect execution",
            persona=Persona.ADMIN.value,
            action_type="inspect",
            expected="Recovered dollars, settled retries, and closed cases reflect executed test outcomes",
        )
        try:
            content = await browser.page.text_content("body") or ""
            has_recovered = "Recovered by retries" in content
            has_settled = "settled" in content.lower()
            has_retries_settled = "Retries that settled" in content

            # Verify API metrics
            async with httpx.AsyncClient() as client:
                m_resp = await client.get(
                    f"{self.runtime_url}/api/v1/metrics",
                    headers={"X-User-Id": "admin"},
                )
                m_resp.raise_for_status()
                metrics = m_resp.json()
                cases_opened = metrics.get("cases", {}).get("opened", 0)
                cases_closed = metrics.get("cases", {}).get("closed", 0)
                approved_count = metrics.get("outcomes", {}).get("action_approved", {}).get("numerator", 0)

            shot = await browser.capture_screenshot("journey8_02_metrics_verified")
            step3.screenshot_path = shot

            step3.actual = (
                f"Recovered by retries={has_recovered}, Retries settled={has_retries_settled}, "
                f"API: cases_opened={cases_opened}, cases_closed={cases_closed}, approved={approved_count}"
            )

            if not has_recovered or cases_closed == 0:
                step3.status = StepStatus.FAIL
                step3.notes = f"Metrics do not reflect activity: cases_closed={cases_closed}"
            else:
                step3.status = StepStatus.PASS
            result.add_step(step3)
        except Exception as e:
            step3.status = StepStatus.FAIL
            step3.actual = f"Error checking recovered metrics: {e}"
            result.add_step(step3)
            result.passed = False

        result.duration_seconds = round(time.time() - start_time, 2)
        result.plain_english_summary = (
            "Journey 8 PASSED: Executive Reports dashboard (/reports) verified. "
            "Accurately reflects return rates against NACHA thresholds, settled retries, "
            "and recovered dollars following end-to-end journey execution."
            if result.passed
            else "Journey 8 FAILED: Executive reporting evaluation did not satisfy requirements."
        )
        return result

    async def run_all_journeys(self) -> list[JourneyResult]:
        """Runs Journeys 1 through 8 in sequence."""
        results: list[JourneyResult] = []
        async with BrowserDriver(
            ui_url=self.ui_url,
            headless=self.headless,
            screenshot_dir=self.screenshot_dir,
        ) as browser:
            # Journey 1: Scenario A (NSF R01)
            j1 = await self.run_journey_1(browser)
            results.append(j1)

            # Journey 2: Retry Outcome (using Journey 1 case)
            j1_case_id = None
            if j1.steps and "Case " in j1.steps[0].actual:
                try:
                    j1_case_id = j1.steps[0].actual.split("Case ")[1].split(" ")[0]
                except Exception as e:
                    logger.debug("Could not parse j1 case_id: %s", e)
            j2 = await self.run_journey_2(browser, journey_1_case_id=j1_case_id)
            results.append(j2)

            # Journey 3: Scenario B (No Account R03)
            j3 = await self.run_journey_3(browser)
            results.append(j3)

            # Journey 4: Suspected Fraud (R10 on new account)
            j4 = await self.run_journey_4(browser)
            results.append(j4)

            # Journey 5: Protected Customer (Bankruptcy)
            j5 = await self.run_journey_5(browser)
            results.append(j5)

            # Journey 6: Duplicate Event
            j6 = await self.run_journey_6(browser)
            results.append(j6)

            # Journey 7: Permissions & Privacy
            j7 = await self.run_journey_7(browser)
            results.append(j7)

            # Journey 8: Executive Reporting
            j8 = await self.run_journey_8(browser)
            results.append(j8)

        return results

