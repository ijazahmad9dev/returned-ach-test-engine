"""Data models for test report summaries and full test report packages."""

from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field

from test_engine.models.result import TestExecutionResult, TestStatus


class CategoryMetrics(BaseModel):
    """Pass/Fail metrics for a specific test category."""
    __test__ = False

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0


class TestReportSummary(BaseModel):
    """Aggregated metrics and metadata for a complete test execution run."""
    __test__ = False

    target_url: str
    execution_mode: str = "mock"
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    pass_rate_pct: float = 0.0
    total_duration_ms: float = 0.0
    is_reachable: bool = True
    health_ok: bool = True
    categories: dict[str, CategoryMetrics] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    @property
    def has_failures(self) -> bool:
        return self.failed > 0 or self.errors > 0 or not self.is_reachable


class FullTestReport(BaseModel):
    """Complete test execution report packaging summary, details, and failure diagnostics."""
    __test__ = False

    summary: TestReportSummary
    results: list[TestExecutionResult] = Field(default_factory=list)
    failure_analysis: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_results(
        cls,
        target_url: str,
        execution_mode: str,
        results: list[TestExecutionResult],
        is_reachable: bool = True,
        health_ok: bool = True,
        failure_analysis: dict[str, Any] | None = None,
    ) -> FullTestReport:
        """Constructs a FullTestReport by computing summary metrics from a results list."""
        total = len(results)
        passed = sum(1 for r in results if r.status == TestStatus.PASS)
        failed = sum(1 for r in results if r.status == TestStatus.FAIL)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
        duration = round(sum(r.execution_time_ms for r in results), 2)
        pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0

        # Category breakdown
        categories: dict[str, CategoryMetrics] = {}
        for r in results:
            cat_name = r.category.value
            if cat_name not in categories:
                categories[cat_name] = CategoryMetrics()
            m = categories[cat_name]
            m.total += 1
            if r.status == TestStatus.PASS:
                m.passed += 1
            elif r.status == TestStatus.FAIL:
                m.failed += 1
            elif r.status == TestStatus.ERROR:
                m.errors += 1
            elif r.status == TestStatus.SKIPPED:
                m.skipped += 1

        summary = TestReportSummary(
            target_url=target_url,
            execution_mode=execution_mode,
            total_tests=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            pass_rate_pct=pass_rate,
            total_duration_ms=duration,
            is_reachable=is_reachable,
            health_ok=health_ok,
            categories=categories,
        )

        return cls(
            summary=summary,
            results=results,
            failure_analysis=failure_analysis or {},
        )
