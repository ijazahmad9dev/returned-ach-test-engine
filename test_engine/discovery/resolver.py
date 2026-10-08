"""Target URL resolver and connectivity inspector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from test_engine.config import EngineConfig
from test_engine.logger import get_logger

logger = get_logger("discovery.resolver")


@dataclass
class TargetResolution:
    """Outcome of resolving and probing a target URL."""

    target_url: str
    base_url: str
    is_single_endpoint: bool
    endpoint_path: str | None
    is_reachable: bool = False
    health_ok: bool = False
    health_data: dict[str, Any] = field(default_factory=dict)
    openapi_url: str | None = None
    status_code: int | None = None
    error_message: str | None = None


class TargetResolver:
    """Inspects target URL, tests connectivity, and resolves OpenAPI specification endpoints."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config

    def parse_target(self, target_url: str) -> tuple[str, bool, str | None]:
        """Splits target_url into (base_url, is_single_endpoint, endpoint_path)."""
        parsed = urlparse(target_url.rstrip("/"))
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path.rstrip("/")
        is_single = bool(path and path != "")
        endpoint_path = path if is_single else None
        return base_url, is_single, endpoint_path

    async def resolve(
        self, client: httpx.AsyncClient | None = None
    ) -> TargetResolution:
        """Probes the target server, verifies health, and discovers OpenAPI availability."""
        target_url = self.config.target_url
        base_url, is_single, endpoint_path = self.parse_target(target_url)

        resolution = TargetResolution(
            target_url=target_url,
            base_url=base_url,
            is_single_endpoint=is_single,
            endpoint_path=endpoint_path,
        )

        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
            close_client = True

        try:
            # 1. Probe health endpoint
            health_candidates = [
                f"{base_url}{self.config.health_path}",
                f"{base_url}/health",
                f"{base_url}/",
            ]
            for health_url in health_candidates:
                try:
                    resp = await client.get(health_url)
                    resolution.is_reachable = True
                    resolution.status_code = resp.status_code
                    if resp.status_code == 200:
                        resolution.health_ok = True
                        try:
                            resolution.health_data = resp.json()
                        except Exception:
                            resolution.health_data = {"raw": resp.text[:200]}
                        logger.info(f"Target health check passed at {health_url}")
                        break
                except httpx.RequestError:
                    continue

            # 2. Probe OpenAPI specifications
            openapi_candidates = [
                f"{base_url}{self.config.openapi_path}",
                f"{base_url}/openapi.json",
                f"{base_url}/api/v1/openapi.json",
                f"{base_url}/swagger.json",
            ]
            for candidate in openapi_candidates:
                try:
                    resp = await client.get(candidate)
                    if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                        resolution.openapi_url = candidate
                        resolution.is_reachable = True
                        logger.info(f"OpenAPI spec discovered at {candidate}")
                        break
                except httpx.RequestError:
                    continue

            # 3. If single endpoint mode, test the specific endpoint directly
            if is_single and endpoint_path:
                try:
                    resp = await client.options(target_url)
                    resolution.is_reachable = True
                    resolution.status_code = resp.status_code
                except httpx.RequestError:
                    pass

        except Exception as e:
            resolution.error_message = str(e)
            logger.warning(f"Error during target resolution for {target_url}: {e}")
        finally:
            if close_client:
                await client.aclose()

        return resolution
