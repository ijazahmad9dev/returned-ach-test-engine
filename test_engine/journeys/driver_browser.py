"""Browser Driver using Playwright.

Acts as personas in the Control Center UI (http://localhost:3000),
inspects visible information (inbox, suggested dates, notices, redactions),
executes human decisions, and captures screenshots for reports.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from test_engine.logger import get_logger

logger = get_logger("journeys.driver_browser")

DEFAULT_UI_URL = "http://localhost:3000"
DEFAULT_SCREENSHOT_DIR = "reports/screenshots"


class BrowserDriver:
    """Automates Control Center UI interactions through Playwright."""

    def __init__(
        self,
        ui_url: str = DEFAULT_UI_URL,
        headless: bool = True,
        screenshot_dir: str = DEFAULT_SCREENSHOT_DIR,
    ) -> None:
        self.ui_url = ui_url.rstrip("/")
        self.headless = headless
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._current_persona: str | None = None

    async def __aenter__(self) -> BrowserDriver:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self) -> None:
        """Launches Playwright and opens a browser context."""
        logger.info("Starting Playwright Chromium (headless=%s)", self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900}
        )
        self._page = await self._context.new_page()

    async def stop(self) -> None:
        """Closes browser and cleans up resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Playwright session terminated")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not started. Call start() or use async with BrowserDriver().")
        return self._page

    async def act_as(self, persona: str) -> None:
        """Switches the active persona by setting localStorage and cookie."""
        self._current_persona = persona
        logger.info("Switching persona to %s", persona)
        # Navigate to base to establish origin
        await self.page.goto(f"{self.ui_url}/", wait_until="domcontentloaded")
        await self.page.evaluate(
            """(userId) => {
                localStorage.setItem("agentos.acting-as", userId);
                document.cookie = `agentos-acting-as=${encodeURIComponent(userId)}; path=/; max-age=31536000; samesite=lax`;
            }""",
            persona,
        )

    async def goto_inbox(self) -> None:
        """Navigates to the Inbox page."""
        await self.page.goto(f"{self.ui_url}/inbox", wait_until="networkidle")

    async def open_task(self, task_id: str) -> None:
        """Navigates directly to a task detail page."""
        url = f"{self.ui_url}/inbox/{task_id}"
        logger.info("Opening task page: %s", url)
        await self.page.goto(url, wait_until="networkidle")

    async def inspect_task(self) -> dict[str, Any]:
        """Inspects and returns what a user actually sees on the task screen."""
        body_text = await self.page.text_content("body") or ""
        buttons = [
            b.strip()
            for b in await self.page.locator("button").all_text_contents()
            if b.strip()
        ]

        # Check for suggested retry date
        date_inputs = self.page.locator("input[type=date]")
        date_val = None
        if await date_inputs.count() > 0:
            date_val = await date_inputs.first.input_value()

        # Check if customer identity is locked/withheld
        locked = "Customer details are hidden for your role" in body_text

        # Detect recommendation
        has_retry_rec = any("Retry the payment" in b for b in buttons)
        has_replacement_rec = any("Ask for a new payment method" in b for b in buttons)
        has_block_account = any("Block account" in b for b in buttons)
        has_cancel_billing = any("Cancel future billing" in b for b in buttons)
        has_open_fraud_inv = (
            any("Open a fraud investigation" in b for b in buttons)
            or "Open a fraud investigation" in body_text
        )
        has_handle_manually = any("Handle manually" in b for b in buttons)

        # Detect priority
        is_urgent = "Urgent" in body_text

        # Detect notice preview
        has_notice_preview = (
            "Message to the customer" in body_text
            or "Your payment of USD" in body_text
            or "We need an updated payment method" in body_text
        )

        return {
            "body_snippet": body_text[:500],
            "buttons": buttons,
            "suggested_date": date_val,
            "customer_identity_locked": locked,
            "is_urgent": is_urgent,
            "has_retry_recommendation": has_retry_rec,
            "has_replacement_recommendation": has_replacement_rec,
            "has_block_account": has_block_account,
            "has_cancel_billing": has_cancel_billing,
            "has_open_fraud_investigation": has_open_fraud_inv,
            "has_handle_manually": has_handle_manually,
            "has_notice_preview": has_notice_preview,
            "full_text": body_text,
        }

    async def select_choice(self, label_fragment: str) -> bool:
        """Clicks an action or recommendation choice button."""
        logger.info("Selecting choice with label: %s", label_fragment)
        btn = self.page.locator("button", has_text=label_fragment).first
        if await btn.count() > 0:
            await btn.click()
            await self.page.wait_for_timeout(600)
            return True
        logger.warning("Button with label %r not found", label_fragment)
        return False

    async def modify_retry_date(self, new_date: str) -> bool:
        """Modifies the retry date in the date input."""
        logger.info("Modifying retry date to %s", new_date)
        date_input = self.page.locator("input[type=date]").first
        if await date_input.count() > 0:
            await date_input.fill(new_date)
            await self.page.wait_for_timeout(600)
            return True
        logger.warning("No date input found to modify")
        return False

    async def confirm_decision(self) -> bool:
        """Clicks the decision confirmation button (e.g. 'Confirm: Retry the payment')."""
        confirm_btn = self.page.locator("button", has_text="Confirm:").first
        if await confirm_btn.count() > 0:
            logger.info("Clicking confirmation button: %s", await confirm_btn.text_content())
            await confirm_btn.click()
            await self.page.wait_for_timeout(2000)
            return True
        logger.warning("No confirmation button found")
        return False

    async def open_fraud_investigation(
        self, reason: str, assignee: str | None = None
    ) -> bool:
        """Opens a fraud investigation via the Control Center UI dialog."""
        logger.info("Opening fraud investigation: reason=%s, assignee=%s", reason, assignee)
        inv_btn = self.page.locator("button", has_text="Open a fraud investigation").first
        if await inv_btn.count() == 0:
            logger.warning("Button 'Open a fraud investigation' not found")
            return False

        await inv_btn.click()
        await self.page.wait_for_timeout(500)

        # Fill why/wrong textarea
        ta = self.page.locator("textarea[placeholder*=\"wrong\"]").first
        if await ta.count() > 0:
            await ta.fill(reason)
            await self.page.wait_for_timeout(300)

        # Optionally select assignee
        if assignee:
            assign_select = self.page.locator("select", has_text="Anyone on the fraud analyst team").first
            if await assign_select.count() > 0:
                await assign_select.select_option(value=assignee)

        # Submit dialog
        submit_btn = self.page.locator("button", has_text="Open fraud investigation").first
        if await submit_btn.count() > 0:
            await submit_btn.click()
            await self.page.wait_for_timeout(1500)
            return True
        return False

    async def block_account(self) -> bool:
        """Selects 'Block account' and confirms decision."""
        logger.info("Selecting 'Block account' and confirming...")
        block_btn = self.page.locator("button", has_text="Block account").first
        if await block_btn.count() > 0:
            await block_btn.click()
            await self.page.wait_for_timeout(600)
            confirm_btn = self.page.locator("button", has_text="Confirm: Block account").first
            if await confirm_btn.count() > 0:
                await confirm_btn.click()
                await self.page.wait_for_timeout(2000)
                return True
        return False

    async def close_with_legal_hold(
        self,
        note: str = "Customer under bankruptcy protection; legal hold applied.",
        resolution_label: str = "Legal or compliance hold",
    ) -> bool:
        """Closes an escalation task by recording a legal reason note and resolution."""
        logger.info("Closing escalation with legal hold: resolution=%s", resolution_label)
        # 1. Fill reason note in textarea
        ta = self.page.locator("textarea[placeholder*=\"why\"]").first
        if await ta.count() > 0:
            await ta.fill(note)
            await self.page.wait_for_timeout(300)

        # 2. Select resolution in dropdown
        select = self.page.locator("select").first
        if await select.count() > 0:
            await select.select_option(label=resolution_label)
            await self.page.wait_for_timeout(500)

        # 3. Confirm handle manually
        confirm_btn = self.page.locator("button", has_text="Confirm: Handle manually").first
        if await confirm_btn.count() > 0:
            await confirm_btn.click()
            await self.page.wait_for_timeout(2000)
            return True
        return False

    async def select_resolution_and_close(self, resolution_label: str) -> bool:
        """Selects a resolution from the dropdown and confirms closing a follow-up task."""
        logger.info("Selecting resolution: %s", resolution_label)
        select = self.page.locator("select").first
        if await select.count() > 0:
            await select.select_option(label=resolution_label)
            await self.page.wait_for_timeout(500)
            confirm_btn = self.page.locator("button", has_text="Confirm: Close the case").first
            if await confirm_btn.count() > 0:
                await confirm_btn.click()
                await self.page.wait_for_timeout(2000)
                return True
        return False

    async def capture_screenshot(self, name: str) -> str:
        """Captures diagnostic screenshot and returns filepath."""
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
        filename = f"{safe_name}.png"
        filepath = self.screenshot_dir / filename
        await self.page.screenshot(path=str(filepath))
        logger.info("Diagnostic screenshot saved to %s", filepath)
        return str(filepath)

    async def get_reports_summary(self) -> dict[str, Any]:
        """Navigates to /reports and inspects visible metrics."""
        await self.page.goto(f"{self.ui_url}/reports", wait_until="networkidle")
        content = await self.page.text_content("body") or ""
        return {
            "has_return_rate": "Return rate" in content,
            "has_unauthorized_rate": "Unauthorized return rate" in content,
            "content_snippet": content[:600],
        }
