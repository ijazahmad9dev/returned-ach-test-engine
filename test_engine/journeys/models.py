"""Domain models for Journey testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Persona(str, Enum):
    """Supported personas for human-in-the-loop journeys."""
    MARCUS = "marcus"          # payments_specialist
    PRIYA = "priya"            # reviewer
    DANA = "dana"              # escalation_owner
    SAM = "sam"                # fraud_analyst
    TOM = "tom"                # collections_specialist
    ADMIN = "admin"            # admin


PERSONA_ROLES: dict[str, str] = {
    Persona.MARCUS.value: "payments_specialist",
    Persona.PRIYA.value: "reviewer",
    Persona.DANA.value: "escalation_owner",
    Persona.SAM.value: "fraud_analyst",
    Persona.TOM.value: "collections_specialist",
    Persona.ADMIN.value: "admin",
}


class StepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    QUESTION = "QUESTION"  # Used when requirement is silent and system made a choice
    SKIP = "SKIP"


@dataclass
class JourneyStep:
    """Represents a single observable step within a user journey."""
    step_id: str
    title: str
    persona: str | None = None
    action_type: str = "inspect"  # trigger, inspect, modify, approve, close, outcome
    expected: str = ""
    actual: str = ""
    status: StepStatus = StepStatus.PASS
    screenshot_path: str | None = None
    notes: str | None = None
    diagnostic_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class JourneyResult:
    """Represents the complete result of executing a user journey."""
    journey_id: str
    name: str
    scenario: str
    passed: bool
    duration_seconds: float = 0.0
    steps: list[JourneyStep] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    plain_english_summary: str = ""

    def add_step(self, step: JourneyStep) -> None:
        self.steps.append(step)
        if step.status == StepStatus.FAIL:
            self.passed = False
        if step.status == StepStatus.QUESTION and step.notes:
            self.open_questions.append(step.notes)
        if step.screenshot_path and step.screenshot_path not in self.screenshots:
            self.screenshots.append(step.screenshot_path)
