"""Unit tests for Stripe and Browser drivers and Journey models."""

import hashlib
import hmac
from pathlib import Path

from test_engine.journeys.driver_browser import BrowserDriver
from test_engine.journeys.driver_stripe import StripeDriver
from test_engine.journeys.models import (
    PERSONA_ROLES,
    JourneyResult,
    JourneyStep,
    Persona,
    StepStatus,
)


def test_persona_roles_mapping():
    """Verifies that all personas map to their expected organizational roles."""
    assert PERSONA_ROLES[Persona.MARCUS.value] == "payments_specialist"
    assert PERSONA_ROLES[Persona.PRIYA.value] == "reviewer"
    assert PERSONA_ROLES[Persona.DANA.value] == "escalation_owner"
    assert PERSONA_ROLES[Persona.SAM.value] == "fraud_analyst"
    assert PERSONA_ROLES[Persona.TOM.value] == "collections_specialist"
    assert PERSONA_ROLES[Persona.ADMIN.value] == "admin"


def test_journey_step_status_tracking():
    """Tests JourneyResult status aggregation from steps."""
    result = JourneyResult(
        journey_id="j_test",
        name="Test Journey",
        scenario="test-scenario",
        passed=True,
    )

    step1 = JourneyStep(step_id="S1", title="Step 1", status=StepStatus.PASS)
    step2 = JourneyStep(
        step_id="S2",
        title="Step 2",
        status=StepStatus.QUESTION,
        notes="Is 4 days business or calendar?",
    )
    result.add_step(step1)
    result.add_step(step2)

    assert result.passed is True
    assert len(result.open_questions) == 1
    assert "Is 4 days business or calendar?" in result.open_questions[0]

    step3 = JourneyStep(step_id="S3", title="Step 3", status=StepStatus.FAIL)
    result.add_step(step3)
    assert result.passed is False


def test_stripe_driver_hmac_signature():
    """Verifies mock webhook HMAC-SHA256 signature computation."""
    driver = StripeDriver(mock_secret="test-secret-123")
    body = b'{"type": "ach.return.created"}'
    sig = driver._sign_mock_webhook(body)

    expected_hash = hmac.new(b"test-secret-123", body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected_hash}"


def test_browser_driver_initialization(tmp_path: Path):
    """Verifies browser driver paths and defaults."""
    screenshots = tmp_path / "screenshots"
    driver = BrowserDriver(
        ui_url="http://localhost:3000",
        headless=True,
        screenshot_dir=str(screenshots),
    )
    assert driver.ui_url == "http://localhost:3000"
    assert driver.headless is True
    assert driver.screenshot_dir.exists()
