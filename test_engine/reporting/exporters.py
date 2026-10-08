"""Multi-Format Test Report Exporters (Console, JSON, Markdown, HTML)."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from test_engine.logger import get_logger
from test_engine.models.report import FullTestReport
from test_engine.models.result import TestStatus

logger = get_logger("reporting.exporters")
console = Console()


class ConsoleExporter:
    """Formats and prints test results to the terminal using Rich."""

    @staticmethod
    def render(report: FullTestReport) -> None:
        summary = report.summary

        # 1. Individual Test Results Table
        table = Table(title="Return ACH Test Execution Results", show_lines=False)
        table.add_column("Status", width=8, justify="center")
        table.add_column("Test ID", style="cyan", width=34)
        table.add_column("Category", style="magenta", width=14)
        table.add_column("HTTP", justify="center", width=6)
        table.add_column("Time", justify="right", width=9)
        table.add_column("Description", style="dim")

        for r in report.results:
            status_style = "bold green" if r.status == TestStatus.PASS else "bold red"
            if r.status == TestStatus.ERROR:
                status_style = "bold yellow"
            elif r.status == TestStatus.SKIPPED:
                status_style = "dim"

            table.add_row(
                f"[{status_style}]{r.status.value}[/{status_style}]",
                r.test_id,
                r.category.value,
                str(r.http_status_code or "-"),
                f"{r.execution_time_ms:.1f}ms",
                r.name,
            )

        console.print(table)

        # 2. Category Summary Table
        cat_table = Table(title="Results by Category", show_lines=False)
        cat_table.add_column("Category", style="bold")
        cat_table.add_column("Total", justify="right")
        cat_table.add_column("Passed", justify="right", style="green")
        cat_table.add_column("Failed", justify="right", style="red")
        cat_table.add_column("Pass Rate", justify="right")

        for cat_name, metrics in summary.categories.items():
            rate = f"{(metrics.passed / metrics.total * 100):.1f}%" if metrics.total > 0 else "0.0%"
            cat_table.add_row(
                cat_name,
                str(metrics.total),
                str(metrics.passed),
                str(metrics.failed + metrics.errors),
                rate,
            )

        console.print(cat_table)

        # 3. Overall Summary Panel
        panel_style = "green" if not summary.has_failures else "red"
        status_text = "PASSED" if not summary.has_failures else "FAILED"

        summary_content = (
            f"[bold {panel_style}]OVERALL STATUS: {status_text}[/bold {panel_style}]\n"
            f"Target: [cyan]{summary.target_url}[/cyan] | Mode: [yellow]{summary.execution_mode}[/yellow]\n"
            f"Tests: [bold]{summary.total_tests}[/bold] | "
            f"Passed: [bold green]{summary.passed}[/bold green] | "
            f"Failed: [bold red]{summary.failed}[/bold red] | "
            f"Errors: [bold yellow]{summary.errors}[/bold yellow]\n"
            f"Pass Rate: [bold]{summary.pass_rate_pct}%[/bold] | "
            f"Total Duration: [bold]{summary.total_duration_ms:.1f}ms[/bold]"
        )
        console.print(Panel(summary_content, title="Test Run Summary", border_style=panel_style))


class JsonExporter:
    """Exports test report as structured machine-readable JSON."""

    @staticmethod
    def export(report: FullTestReport, output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))
        logger.info(f"JSON test report saved to {output_file}")
        return output_file


class MarkdownExporter:
    """Exports test report as GitHub-flavored Markdown."""

    @staticmethod
    def export(report: FullTestReport, output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        summary = report.summary
        status_badge = "✅ PASSED" if not summary.has_failures else "❌ FAILED"

        lines: list[str] = [
            "# Return ACH Test Engine Report",
            "",
            f"**Overall Status:** {status_badge}  ",
            f"**Target URL:** `{summary.target_url}`  ",
            f"**Execution Mode:** `{summary.execution_mode}`  ",
            f"**Pass Rate:** {summary.pass_rate_pct}%  ",
            f"**Total Duration:** {summary.total_duration_ms} ms  ",
            "",
            "## Summary Metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total Tests | {summary.total_tests} |",
            f"| Passed | {summary.passed} |",
            f"| Failed | {summary.failed} |",
            f"| Errors | {summary.errors} |",
            f"| Skipped | {summary.skipped} |",
            f"| Pass Rate | {summary.pass_rate_pct}% |",
            "",
            "## Category Breakdown",
            "",
            "| Category | Total | Passed | Failed/Errors | Pass Rate |",
            "|---|---|---|---|---|",
        ]

        for cat_name, metrics in summary.categories.items():
            rate = f"{(metrics.passed / metrics.total * 100):.1f}%" if metrics.total > 0 else "0.0%"
            lines.append(
                f"| `{cat_name}` | {metrics.total} | {metrics.passed} | {metrics.failed + metrics.errors} | {rate} |"
            )

        lines.extend([
            "",
            "## Test Results Detail",
            "",
            "| Status | Test ID | Category | HTTP | Duration | Description |",
            "|---|---|---|---|---|---|",
        ])

        for r in report.results:
            icon = "✅" if r.status == TestStatus.PASS else ("⚠️" if r.status == TestStatus.ERROR else "❌")
            lines.append(
                f"| {icon} {r.status.value} | `{r.test_id}` | {r.category.value} | {r.http_status_code or '-'} | {r.execution_time_ms:.1f}ms | {r.name} |"
            )

        # Failures section
        failed_tests = [r for r in report.results if r.status in (TestStatus.FAIL, TestStatus.ERROR)]
        if failed_tests:
            lines.extend([
                "",
                "## Failure Diagnostics & Diffs",
                "",
            ])
            for ft in failed_tests:
                lines.extend([
                    f"### ❌ {ft.test_id}: {ft.name}",
                    f"- **URL:** `{ft.request_method} {ft.request_url}`",
                    f"- **Received Status:** `{ft.http_status_code}` (Expected: `{ft.expected_status_code}`)",
                    f"- **Validation Failures:**",
                ])
                for fail_msg in ft.validation_failures:
                    lines.append(f"  - {fail_msg}")
                if ft.diff_summary:
                    lines.extend([
                        "- **Diff Summary:**",
                        "```text",
                        ft.diff_summary,
                        "```",
                    ])
                if ft.logs:
                    lines.extend([
                        "- **Execution Logs:**",
                        "```text",
                        ft.logs,
                        "```",
                    ])
                lines.append("")

        with output_file.open("w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info(f"Markdown test report saved to {output_file}")
        return output_file


class HtmlExporter:
    """Exports test report as a self-contained, interactive HTML dashboard."""

    @staticmethod
    def export(report: FullTestReport, output_file: Path) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        summary = report.summary
        is_passed = not summary.has_failures

        # Build HTML content
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Return ACH Test Report</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --border: #334155;
      --pass: #10b981;
      --fail: #ef4444;
      --warn: #f59e0b;
      --accent: #38bdf8;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 24px;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px; }}
    .badge {{ padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 14px; text-transform: uppercase; }}
    .badge-pass {{ background: rgba(16, 185, 129, 0.2); color: var(--pass); border: 1px solid var(--pass); }}
    .badge-fail {{ background: rgba(239, 68, 68, 0.2); color: var(--fail); border: 1px solid var(--fail); }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .kpi-card {{ background: var(--card-bg); padding: 16px; border-radius: 8px; border: 1px solid var(--border); }}
    .kpi-title {{ font-size: 12px; color: var(--text-dim); text-transform: uppercase; margin-bottom: 4px; }}
    .kpi-value {{ font-size: 28px; font-weight: bold; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; background: var(--card-bg); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }}
    th {{ background: #0f172a; color: var(--text-dim); font-size: 12px; text-transform: uppercase; }}
    tr:hover {{ background: rgba(255, 255, 255, 0.02); }}
    .status-tag {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
    .tag-pass {{ background: var(--pass); color: #000; }}
    .tag-fail {{ background: var(--fail); color: #fff; }}
    .tag-error {{ background: var(--warn); color: #000; }}
    pre {{ background: #0f172a; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; color: var(--accent); }}
    details {{ margin-top: 8px; }}
    summary {{ cursor: pointer; color: var(--accent); font-size: 12px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 style="margin:0 0 4px 0;">Return ACH Test Engine Report</h1>
        <div style="color:var(--text-dim); font-size:14px;">
          Target: <code style="color:var(--accent);">{html.escape(summary.target_url)}</code> | Mode: <strong>{summary.execution_mode}</strong>
        </div>
      </div>
      <div>
        <span class="badge {'badge-pass' if is_passed else 'badge-fail'}">
          { 'Passed' if is_passed else 'Failed' }
        </span>
      </div>
    </div>

    <div class="kpis">
      <div class="kpi-card">
        <div class="kpi-title">Total Tests</div>
        <div class="kpi-value">{summary.total_tests}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Passed</div>
        <div class="kpi-value" style="color:var(--pass);">{summary.passed}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Failed</div>
        <div class="kpi-value" style="color:var(--fail);">{summary.failed}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Pass Rate</div>
        <div class="kpi-value">{summary.pass_rate_pct}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Total Duration</div>
        <div class="kpi-value">{summary.total_duration_ms:.0f} ms</div>
      </div>
    </div>

    <h2>Test Execution Details</h2>
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>ID</th>
          <th>Category</th>
          <th>HTTP</th>
          <th>Latency</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
"""
        for r in report.results:
            tag_class = "tag-pass" if r.status == TestStatus.PASS else ("tag-error" if r.status == TestStatus.ERROR else "tag-fail")
            diff_block = ""
            if r.diff_summary:
                diff_block = f"<details><summary>View Diff / Diagnostics</summary><pre>{html.escape(r.diff_summary)}</pre></details>"

            html_content += f"""
        <tr>
          <td><span class="status-tag {tag_class}">{r.status.value}</span></td>
          <td><code>{html.escape(r.test_id)}</code></td>
          <td>{r.category.value}</td>
          <td>{r.http_status_code or '-'}</td>
          <td>{r.execution_time_ms:.1f}ms</td>
          <td>
            <strong>{html.escape(r.name)}</strong>
            <div style="color:var(--text-dim);font-size:12px;">{html.escape(r.description)}</div>
            {diff_block}
          </td>
        </tr>
"""

        html_content += """
      </tbody>
    </table>
  </div>
</body>
</html>
"""

        with output_file.open("w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"HTML test report saved to {output_file}")
        return output_file


class ReportExporterManager:
    """Manages exporting test reports across all requested formats."""

    @staticmethod
    def export_all(
        report: FullTestReport,
        output_dir: Path,
        formats: list[str] | None = None,
    ) -> dict[str, Path]:
        """Generates report artifacts for all specified formats."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        formats = formats or ["console", "json", "markdown", "html"]

        exported_paths: dict[str, Path] = {}

        if "console" in formats:
            ConsoleExporter.render(report)

        if "json" in formats:
            json_path = output_dir / "report.json"
            JsonExporter.export(report, json_path)
            exported_paths["json"] = json_path

        if "markdown" in formats:
            md_path = output_dir / "report.md"
            MarkdownExporter.export(report, md_path)
            exported_paths["markdown"] = md_path

        if "html" in formats:
            html_path = output_dir / "report.html"
            HtmlExporter.export(report, html_path)
            exported_paths["html"] = html_path

        return exported_paths
