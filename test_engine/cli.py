"""Command Line Interface for Return ACH Test Engine."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from test_engine import __version__
from test_engine.config import EngineConfig, ExecutionMode
from test_engine.logger import get_logger, setup_logger
from test_engine.models.report import FullTestReport
from test_engine.models.result import TestExecutionResult
from test_engine.orchestration.graph import run_test_workflow
from test_engine.reporting.exporters import ReportExporterManager

console = Console()
logger = get_logger("cli")


@click.group()
@click.version_option(version=__version__, prog_name="ach-test")
def main() -> None:
    """Return ACH Test Engine - Automated testing for Return ACH resolution systems."""
    pass


@main.command()
@click.option(
    "--url",
    "-u",
    default="http://localhost:8000",
    help="Target base backend URL or specific endpoint URL (default: http://localhost:8000)",
)
@click.option(
    "--mode",
    "-m",
    type=click.Choice(["mock", "real"], case_sensitive=False),
    default="mock",
    help="Execution mode: mock or real connectors (default: mock)",
)
@click.option(
    "--suites",
    "-s",
    multiple=True,
    help="Test suites to execute (e.g., health, schema, ach_domain, security, connectors, all)",
)
@click.option(
    "--concurrency",
    "-c",
    type=int,
    default=5,
    help="Concurrency limit for async HTTP testing (default: 5)",
)
@click.option(
    "--timeout",
    "-t",
    type=float,
    default=15.0,
    help="HTTP request timeout in seconds (default: 15.0)",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    help="Directory to save test reports and artifacts (default: reports)",
)
@click.option(
    "--format",
    "-f",
    "report_formats",
    multiple=True,
    type=click.Choice(["console", "json", "markdown", "html"], case_sensitive=False),
    help="Report formats to generate (default: all)",
)
@click.option(
    "--config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Path to YAML configuration file",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output and wire logging",
)
def run(
    url: str,
    mode: str,
    suites: tuple[str, ...],
    concurrency: int,
    timeout: float,
    output_dir: Path,
    report_formats: tuple[str, ...],
    config: Optional[Path],
    verbose: bool,
) -> None:
    """Execute the Return ACH test engine against a target API."""
    setup_logger(level="DEBUG" if verbose else "INFO", verbose=verbose)

    overrides = {
        "target_url": url,
        "execution_mode": ExecutionMode(mode.lower()),
        "max_concurrency": concurrency,
        "timeout_seconds": timeout,
        "output_dir": output_dir,
        "verbose": verbose,
    }
    if suites:
        overrides["suites"] = list(suites)
    if report_formats:
        overrides["report_formats"] = list(report_formats)

    if config:
        cfg = EngineConfig.from_yaml(config, **overrides)
    else:
        cfg = EngineConfig(**overrides)

    console.print(
        f"[bold cyan]Return ACH Test Engine v{__version__}[/bold cyan] starting...",
        style="bold",
    )
    console.print(f"Target: [green]{cfg.target_url}[/green]")
    console.print(f"Mode: [yellow]{cfg.execution_mode.value}[/yellow]")
    console.print(f"Suites: [magenta]{', '.join(cfg.suites)}[/magenta]")

    async def _run() -> int:
        final_state = await run_test_workflow(cfg)

        raw_results = final_state.get("execution_results", [])
        results = [TestExecutionResult.model_validate(r) for r in raw_results]

        report = FullTestReport.from_results(
            target_url=cfg.target_url,
            execution_mode=cfg.execution_mode.value,
            results=results,
            is_reachable=final_state.get("is_reachable", False),
            health_ok=final_state.get("health_ok", False),
            failure_analysis=final_state.get("failure_analysis", {}),
        )

        ReportExporterManager.export_all(
            report=report,
            output_dir=cfg.output_dir,
            formats=cfg.report_formats,
        )

        return 1 if report.summary.has_failures else 0

    exit_code = asyncio.run(_run())
    if exit_code != 0:
        sys.exit(exit_code)


@main.command()
@click.option(
    "--url",
    "-u",
    default="http://localhost:8000",
    help="Target base backend URL or specific endpoint to inspect",
)
def discover(url: str) -> None:
    """Inspect and display API contracts and endpoints from the target server."""
    from rich.table import Table
    from test_engine.discovery.contract_analyzer import ContractAnalyzer
    from test_engine.discovery.openapi_fetcher import OpenApiFetcher
    from test_engine.discovery.resolver import TargetResolver

    setup_logger()
    cfg = EngineConfig(target_url=url)
    console.print(f"[bold cyan]Inspecting target:[/bold cyan] {cfg.target_url}")

    async def _run_discover() -> None:
        resolver = TargetResolver(cfg)
        resolution = await resolver.resolve()

        if not resolution.is_reachable:
            console.print(f"[bold red]Target is unreachable:[/bold red] {resolution.target_url}")
            if resolution.error_message:
                console.print(f"Error: {resolution.error_message}")
            return

        console.print(f"Health Status: {'[green]OK[/green]' if resolution.health_ok else '[yellow]Unavailable[/yellow]'}")
        if resolution.openapi_url:
            console.print(f"OpenAPI Spec URL: [green]{resolution.openapi_url}[/green]")
            fetcher = OpenApiFetcher(timeout_seconds=cfg.timeout_seconds)
            try:
                raw_spec = await fetcher.fetch(resolution.openapi_url)
                analyzer = ContractAnalyzer(fetcher)
                contract = analyzer.analyze(
                    spec=raw_spec,
                    base_url=resolution.base_url,
                    target_url=resolution.target_url,
                    is_single_endpoint_mode=resolution.is_single_endpoint,
                    single_path=resolution.endpoint_path,
                    health_ok=resolution.health_ok,
                    health_details=resolution.health_data,
                )

                table = Table(title=f"Discovered Endpoints ({contract.title} v{contract.version})")
                table.add_column("Method", style="bold green", width=8)
                table.add_column("Path", style="cyan")
                table.add_column("Auth", style="yellow", width=8)
                table.add_column("Params", style="magenta", width=12)
                table.add_column("Body Schema", style="blue", width=14)
                table.add_column("Tags", style="dim")

                for ep in contract.endpoints:
                    auth_str = "Required" if ep.requires_auth else "None"
                    params_str = f"{len(ep.parameters)} param(s)" if ep.parameters else "-"
                    body_str = f"{len(ep.field_rules)} fields" if ep.field_rules else ("Yes" if ep.request_schema else "No")
                    table.add_row(
                        ep.method,
                        ep.path,
                        auth_str,
                        params_str,
                        body_str,
                        ", ".join(ep.tags),
                    )

                console.print(table)
                console.print(f"Total discovered operations: [bold green]{len(contract.endpoints)}[/bold green]")
            except Exception as e:
                console.print(f"[bold red]Failed to fetch or parse OpenAPI spec:[/bold red] {e}")
        else:
            console.print("[yellow]No OpenAPI spec endpoint found. Fallback contract mode active.[/yellow]")

    asyncio.run(_run_discover())


@main.command()
@click.option(
    "--input",
    "-i",
    "input_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to report.json artifact file",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("reports"),
    help="Directory to save exported reports",
)
@click.option(
    "--format",
    "-f",
    "report_formats",
    multiple=True,
    type=click.Choice(["console", "markdown", "html"], case_sensitive=False),
    help="Report formats to export",
)
def report(input_path: Path, output_dir: Path, report_formats: tuple[str, ...]) -> None:
    """Re-export and display test results from a saved JSON report."""
    setup_logger()
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    full_report = FullTestReport.model_validate(data)
    formats = list(report_formats) if report_formats else ["console", "markdown", "html"]

    exported = ReportExporterManager.export_all(
        report=full_report,
        output_dir=output_dir,
        formats=formats,
    )
    for fmt, path in exported.items():
        console.print(f"Generated {fmt.upper()} report at: [green]{path}[/green]")


@main.command()
@click.option(
    "--host",
    "-h",
    default="127.0.0.1",
    help="Host to bind the web server (default: 127.0.0.1)",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=8080,
    help="Port to serve the dashboard on (default: 8080)",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development",
)
def ui(host: str, port: int, reload: bool) -> None:
    """Launch the Return ACH Test Engine interactive Web Dashboard."""
    import uvicorn
    from test_engine.server import create_app

    setup_logger()
    console.print("[bold cyan]Launching Return ACH Test Engine Web Dashboard...[/bold cyan]")
    console.print(f"Open in browser: [bold green]http://{host}:{port}[/bold green]")
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
