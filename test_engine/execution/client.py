"""Async HTTP client for test scenario execution."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from test_engine.config import EngineConfig
from test_engine.logger import get_logger

logger = get_logger("execution.client")


@dataclass
class ExecutionResponse:
    """Captured HTTP response with performance metrics."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any | None = None
    text: str = ""
    latency_ms: float = 0.0
    error: str | None = None


class ExecutionHttpClient:
    """Async HTTP client executing test requests with timing and transient error retries."""

    def __init__(self, config: EngineConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._external_client = client
        self._internal_client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Returns the active or pooled HTTP client."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=self.config.max_concurrency * 2,
            )
            self._internal_client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                limits=limits,
            )
        return self._internal_client

    async def execute(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        raw_body: str | None = None,
    ) -> ExecutionResponse:
        """Executes a single HTTP request with retries and precise latency measurement."""
        client = await self.get_client()

        # Merge headers
        req_headers = {
            "Accept": "application/json",
            **self.config.custom_headers,
            **(headers or {}),
        }
        if "X-User-Id" not in req_headers and self.config.auth_user_id:
            req_headers["X-User-Id"] = self.config.auth_user_id

        # Prepare request content
        content = None
        json_payload = None
        if raw_body is not None:
            content = raw_body.encode("utf-8")
            if "Content-Type" not in req_headers:
                req_headers["Content-Type"] = "application/json"
        elif json_body is not None:
            json_payload = json_body

        retries_left = self.config.max_retries
        backoff = self.config.retry_backoff_seconds

        while True:
            t0 = time.perf_counter()
            try:
                response = await client.request(
                    method=method.upper(),
                    url=path,
                    params=params,
                    headers=req_headers,
                    json=json_payload,
                    content=content,
                )
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)

                parsed_json = None
                try:
                    parsed_json = response.json()
                except Exception:
                    pass

                return ExecutionResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    json_body=parsed_json,
                    text=response.text,
                    latency_ms=latency_ms,
                )

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                if retries_left > 0:
                    retries_left -= 1
                    logger.warning(
                        f"Transient error on {method} {path} ({exc}). "
                        f"Retrying in {backoff}s ({retries_left} retries left)..."
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 1.5
                    continue

                return ExecutionResponse(
                    status_code=503,
                    latency_ms=latency_ms,
                    text=str(exc),
                    error=f"Connection failure: {type(exc).__name__}: {exc}",
                )

            except Exception as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000, 2)
                return ExecutionResponse(
                    status_code=500,
                    latency_ms=latency_ms,
                    text=str(exc),
                    error=f"Request error: {type(exc).__name__}: {exc}",
                )

    async def close(self) -> None:
        """Closes internal HTTP client if opened."""
        if self._internal_client and not self._internal_client.is_closed:
            await self._internal_client.aclose()
