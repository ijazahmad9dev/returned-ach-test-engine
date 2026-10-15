"""Stripe & Payment Processor Driver.

Injects failing and retried ACH debits into AgentOS via Stripe sandbox
or the local signed mock processor webhook / demo endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import date
from typing import Any
from uuid import uuid4

import httpx

from test_engine.logger import get_logger

logger = get_logger("journeys.driver_stripe")

DEFAULT_MOCK_SECRET = "local-ui-mock-processor"
DEFAULT_RUNTIME_URL = "http://localhost:8000"


class StripeDriver:
    """Driver to create ACH returns and retried outcomes in Stripe sandbox or mock processor."""

    def __init__(
        self,
        runtime_url: str = DEFAULT_RUNTIME_URL,
        mock_secret: str | None = None,
        stripe_api_key: str | None = None,
    ) -> None:
        self.runtime_url = runtime_url.rstrip("/")
        self.mock_secret = (
            mock_secret
            or os.environ.get("AGENTOS_WEBHOOK_SECRET_MOCK_PROCESSOR")
            or DEFAULT_MOCK_SECRET
        )
        self.stripe_api_key = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY")

    def _sign_mock_webhook(self, body_bytes: bytes) -> str:
        """Computes HMAC-SHA256 signature for mock processor webhook."""
        sig = hmac.new(self.mock_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    async def _get_case(self, case_id: str, user_id: str = "admin") -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.runtime_url}/api/v1/cases/{case_id}",
                headers={"X-User-Id": user_id},
            )
            resp.raise_for_status()
            return resp.json()

    async def trigger_mock_return(
        self,
        return_code: str,
        amount_minor: int,
        trace_number: str,
        account_ref: str = "ACC-0001",
        customer_ref: str = "CUS-0001",
        mandate_ref: str = "AUTH-0001",
        returned_on: str | None = None,
    ) -> dict[str, Any]:
        """Sends a signed ach.return.created event to the mock processor webhook."""
        settlement_date = returned_on or "2026-10-12"
        payload = {
            "id": f"evt_{uuid4().hex[:16]}",
            "type": "ach.return.created",
            "created": date.today().isoformat(),
            "data": {
                "tenant": "tenant_default",
                "original_trace": trace_number,
                "amount": amount_minor,
                "currency": "usd",
                "account": account_ref,
                "customer": customer_ref,
                "mandate": mandate_ref,
                "return_code": return_code.upper(),
                "returned_on": settlement_date,
            },
        }

        body_bytes = json.dumps(payload).encode()
        signature = self._sign_mock_webhook(body_bytes)

        url = f"{self.runtime_url}/api/v1/webhooks/returned-ach/mock_processor"
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, content=body_bytes, headers=headers)
            logger.info("Mock return webhook response [%d]: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            case_id = results[0].get("case_id") if results else None
            return {
                "status_code": resp.status_code,
                "case_id": case_id,
                "created": results[0].get("created", False) if results else False,
                "raw": data,
            }

    async def trigger_demo_scenario(self, eval_id: str, fresh: bool = True) -> dict[str, Any]:
        """Triggers a named demo scenario (e.g. ACH-52 for Scenario A, ACH-53 for Scenario B)."""
        url = f"{self.runtime_url}/api/v1/demo/scenarios/returned-ach/{eval_id}"
        params = {"fresh": "true"} if fresh else {}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params=params, headers={"Content-Type": "application/json"})
            logger.info("Demo scenario trigger [%d]: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()

    async def report_retry_outcome(
        self,
        case_id: str,
        outcome: str,  # 'settle' or 'bounce'
    ) -> dict[str, Any]:
        """Reports outcome of a retry on a case:

        'settle' -> ach.retry.succeeded (retry settled)
        'bounce' -> ach.retry.returned (retry returned / failed again)
        """
        event_type = "ach.retry.succeeded" if outcome == "settle" else "ach.retry.returned"
        url = f"{self.runtime_url}/api/v1/demo/cases/{case_id}/processor-events"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"type": event_type})
            logger.info("Report retry outcome [%d]: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()

    async def get_or_create_scenario_a_case(self) -> dict[str, Any]:
        """Triggers a fresh Scenario A demo case (ACH-52 / TRC-SCENARIO-A)."""
        demo_res = await self.trigger_demo_scenario("ACH-52", fresh=True)
        case_id = demo_res.get("case_id")
        if case_id:
            case_data = await self._get_case(case_id, user_id="marcus")
            open_task = case_data.get("open_task") or {}
            demo_res["task_id"] = open_task.get("id")
        return demo_res

    async def get_or_create_scenario_b_case(self) -> dict[str, Any]:
        """Triggers a fresh Scenario B demo case (ACH-53 / TRC-SCENARIO-B)."""
        demo_res = await self.trigger_demo_scenario("ACH-53", fresh=True)
        case_id = demo_res.get("case_id")
        if case_id:
            case_data = await self._get_case(case_id, user_id="priya")
            open_task = case_data.get("open_task") or {}
            demo_res["task_id"] = open_task.get("id")
        return demo_res

    async def get_or_create_fraud_case(self) -> dict[str, Any]:
        """Triggers a fresh Suspected Fraud demo case (ACH-47 / TRC-R10-FRAUD)."""
        demo_res = await self.trigger_demo_scenario("ACH-47", fresh=True)
        case_id = demo_res.get("case_id")
        if case_id:
            case_data = await self._get_case(case_id, user_id="sam")
            open_task = case_data.get("open_task") or {}
            demo_res["task_id"] = open_task.get("id")
        return demo_res

    async def get_or_create_protected_case(self) -> dict[str, Any]:
        """Triggers a fresh Protected Customer (Bankruptcy) demo case (ACH-08 / TRC-PROTECTED)."""
        demo_res = await self.trigger_demo_scenario("ACH-08", fresh=True)
        case_id = demo_res.get("case_id")
        if case_id:
            case_data = await self._get_case(case_id, user_id="dana")
            open_task = case_data.get("open_task") or {}
            demo_res["task_id"] = open_task.get("id")
        return demo_res


