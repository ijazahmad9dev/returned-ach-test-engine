"""FastAPI web server serving the test engine REST API and frontend dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from test_engine import __version__
from test_engine.config import EngineConfig, ExecutionMode
from test_engine.discovery.contract_analyzer import ContractAnalyzer
from test_engine.discovery.openapi_fetcher import OpenApiFetcher
from test_engine.discovery.resolver import TargetResolver
from test_engine.logger import get_logger
from test_engine.models.report import FullTestReport
from test_engine.models.result import TestExecutionResult
from test_engine.orchestration.graph import run_test_workflow
from test_engine.reporting.exporters import MarkdownExporter, ReportExporterManager

logger = get_logger("server")

STATIC_DIR = Path(__file__).parent / "static"


class DiscoverRequest(BaseModel):
    target_url: str = Field(default="http://localhost:8000")
    timeout_seconds: float = Field(default=10.0)


class RunRequest(BaseModel):
    target_url: str = Field(default="http://localhost:8000")
    execution_mode: str = Field(default="mock")
    suites: list[str] = Field(default_factory=lambda: ["health", "schema", "ach_domain", "security", "connectors"])
    max_concurrency: int = Field(default=5)
    timeout_seconds: float = Field(default=15.0)
    auth_user_id: str = Field(default="usr_test_operator_01")
    tenant_id: str = Field(default="tenant_qa_01")
    output_dir: str = Field(default="reports")
    report_formats: list[str] = Field(default_factory=lambda: ["json", "markdown", "html"])


def create_app() -> FastAPI:
    """Builds and configures the FastAPI test engine server application."""
    app = FastAPI(
        title="Return ACH Test Engine UI",
        version=__version__,
        description="Interactive Web UI and REST API for the Return ACH Test Engine",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "engine_version": __version__,
            "service": "returned-ach-test-engine",
        }

    @app.post("/api/discover")
    async def discover_api(req: DiscoverRequest) -> dict[str, Any]:
        """Probes target URL and extracts API contracts."""
        cfg = EngineConfig(target_url=req.target_url, timeout_seconds=req.timeout_seconds)
        resolver = TargetResolver(cfg)
        resolution = await resolver.resolve()

        if not resolution.is_reachable:
            return {
                "is_reachable": False,
                "health_ok": False,
                "target_url": req.target_url,
                "error_message": resolution.error_message or "Target server is unreachable",
                "endpoints": [],
            }

        contract_data = None
        if resolution.openapi_url:
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
                contract_data = contract.model_dump(mode="json")
            except Exception as e:
                logger.warning(f"Error fetching/parsing OpenAPI: {e}")

        if not contract_data:
            analyzer = ContractAnalyzer()
            fallback = analyzer.create_fallback_contract(
                base_url=resolution.base_url,
                target_url=resolution.target_url,
                endpoint_path=resolution.endpoint_path or "/api/v1/health",
                health_ok=resolution.health_ok,
            )
            contract_data = fallback.model_dump(mode="json")

        return {
            "is_reachable": True,
            "health_ok": resolution.health_ok,
            "health_data": resolution.health_data,
            "openapi_url": resolution.openapi_url,
            "target_url": req.target_url,
            "contract": contract_data,
        }

    @app.post("/api/run")
    async def run_tests(req: RunRequest) -> dict[str, Any]:
        """Executes the full LangGraph testing workflow and exports reports."""
        cfg = EngineConfig(
            target_url=req.target_url,
            execution_mode=ExecutionMode(req.execution_mode.lower()),
            suites=req.suites,
            max_concurrency=req.max_concurrency,
            timeout_seconds=req.timeout_seconds,
            auth_user_id=req.auth_user_id,
            tenant_id=req.tenant_id,
            output_dir=Path(req.output_dir),
            report_formats=req.report_formats,  # pyright: ignore[reportArgumentType]
        )

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

        # Export artifacts to disk
        exported_paths = ReportExporterManager.export_all(
            report=report,
            output_dir=cfg.output_dir,
            formats=cfg.report_formats,
        )

        exported_files = {k: str(v.name) for k, v in exported_paths.items()}

        # Also preserve a timestamped copy for historical comparison
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if "json" in exported_paths and exported_paths["json"].is_file():
            shutil.copy2(exported_paths["json"], cfg.output_dir / f"report_{ts_str}.json")
        if "markdown" in exported_paths and exported_paths["markdown"].is_file():
            shutil.copy2(exported_paths["markdown"], cfg.output_dir / f"report_{ts_str}.md")
        if "html" in exported_paths and exported_paths["html"].is_file():
            shutil.copy2(exported_paths["html"], cfg.output_dir / f"report_{ts_str}.html")

        return {
            "status": "completed" if not report.summary.has_failures else "failed",
            "report": report.model_dump(mode="json"),
            "exported_files": exported_files,
            "workflow_status": final_state.get("workflow_status"),
        }

    @app.get("/api/reports")
    async def list_reports(output_dir: str = "reports") -> list[dict[str, Any]]:
        """Lists previously generated test reports from disk."""
        reports_path = Path(output_dir)
        if not reports_path.is_dir():
            return []

        items: list[dict[str, Any]] = []
        for file in sorted(reports_path.glob("*.json"), reverse=True):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                summary = data.get("summary", {})
                md_name = file.name.replace(".json", ".md")
                items.append({
                    "filename": file.name,
                    "md_filename": md_name,
                    "target_url": summary.get("target_url"),
                    "total_tests": summary.get("total_tests"),
                    "passed": summary.get("passed"),
                    "failed": summary.get("failed"),
                    "pass_rate_pct": summary.get("pass_rate_pct"),
                    "timestamp": summary.get("timestamp"),
                })
            except Exception:
                continue
        return items

    @app.get("/api/reports/{filename}")
    async def get_report_file(
        filename: str,
        output_dir: str = "reports",
        download: bool = False,
    ) -> Any:
        """Retrieves or downloads a specific report artifact file (json, markdown, html)."""
        reports_dir = Path(output_dir).resolve()
        file_path = (reports_dir / filename).resolve()
        if not file_path.is_relative_to(reports_dir):
            raise HTTPException(status_code=400, detail="Invalid report path")

        # Dynamic markdown generation if requesting .md and only .json exists
        if not file_path.is_file() and filename.endswith(".md"):
            json_counterpart = reports_dir / filename.replace(".md", ".json")
            if json_counterpart.is_file():
                try:
                    data = json.loads(json_counterpart.read_text(encoding="utf-8"))
                    report = FullTestReport.model_validate(data)
                    MarkdownExporter.export(report, file_path)
                except Exception as e:
                    logger.warning(f"Could not dynamically generate markdown for {filename}: {e}")

        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Report file not found")

        if download:
            media_type = (
                "application/json"
                if filename.endswith(".json")
                else (
                    "text/markdown"
                    if filename.endswith(".md")
                    else (
                        "text/html"
                        if filename.endswith(".html")
                        else "application/octet-stream"
                    )
                )
            )
            return FileResponse(
                path=file_path,
                media_type=media_type,
                filename=filename,
            )

        if filename.endswith(".html"):
            return HTMLResponse(content=file_path.read_text(encoding="utf-8"))
        elif filename.endswith(".json"):
            return JSONResponse(content=json.loads(file_path.read_text(encoding="utf-8")))
        elif filename.endswith(".md"):
            return Response(content=file_path.read_text(encoding="utf-8"), media_type="text/markdown")
        return FileResponse(path=file_path)

    # Static assets and frontend SPA routing
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", response_class=HTMLResponse)
        async def serve_index() -> HTMLResponse:
            index_file = STATIC_DIR / "index.html"
            if index_file.is_file():
                return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
            return HTMLResponse("<h1>Return ACH Test Engine Frontend - Not Built Yet</h1>")

    return app
