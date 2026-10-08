"""Diff and Failure Analyzer for test responses."""

from __future__ import annotations

import json
from typing import Any


class DiffAnalyzer:
    """Analyzes differences between expected and actual test responses and generates readable diffs."""

    @staticmethod
    def format_diff(
        expected_status: Any,
        actual_status: int,
        expected_error_code: str | None,
        actual_error_code: str | None,
        expected_field: str | None,
        actual_fields: list[str],
        missing_keys: list[str],
    ) -> str:
        """Formats a human-readable diagnostic summary of validation discrepancies."""
        lines: list[str] = []

        status_mismatch = (
            actual_status not in expected_status
            if isinstance(expected_status, list)
            else actual_status != expected_status
        )
        if status_mismatch:
            lines.append(f"• HTTP Status Mismatch: expected {expected_status}, received {actual_status}")

        if expected_error_code and (not actual_error_code or expected_error_code.lower() != actual_error_code.lower()):
            lines.append(
                f"• Error Code Mismatch: expected '{expected_error_code}', received '{actual_error_code or 'None'}'"
            )

        if expected_field and expected_field not in actual_fields:
            lines.append(
                f"• Missing Expected Error Field: '{expected_field}' not in returned field errors: {actual_fields}"
            )

        if missing_keys:
            lines.append(f"• Missing Expected Response Keys: {', '.join(missing_keys)}")

        return "\n".join(lines) if lines else "No structural differences detected."

    @staticmethod
    def extract_error_info(response_json: Any) -> tuple[str | None, list[str]]:
        """Extracts (code, [field_paths]) from AgentOS ErrorEnvelope."""
        if not isinstance(response_json, dict):
            return None, []

        error_obj = response_json.get("error")
        if not isinstance(error_obj, dict):
            return None, []

        code = error_obj.get("code")
        fields = error_obj.get("fields", [])
        field_paths: list[str] = []

        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, dict) and "path" in f:
                    field_paths.append(str(f["path"]))
                elif isinstance(f, str):
                    field_paths.append(f)

        return str(code) if code else None, field_paths
