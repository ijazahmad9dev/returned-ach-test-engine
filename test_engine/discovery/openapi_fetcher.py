"""OpenAPI specification fetcher and JSON schema dereferencer."""

from __future__ import annotations

import copy
from typing import Any

import httpx

from test_engine.logger import get_logger

logger = get_logger("discovery.openapi_fetcher")


class OpenApiFetcher:
    """Fetches and parses OpenAPI specification documents from target servers."""

    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def fetch(
        self, openapi_url: str, client: httpx.AsyncClient | None = None
    ) -> dict[str, Any]:
        """Fetches the OpenAPI JSON schema over HTTP."""
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        try:
            response = await client.get(openapi_url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            logger.info(
                f"Successfully retrieved OpenAPI spec from {openapi_url} "
                f"(title='{data.get('info', {}).get('title')}', version='{data.get('info', {}).get('version')}')"
            )
            return data
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def dereference_schema(
        schema: Any, components_schemas: dict[str, Any], seen_refs: set[str] | None = None
    ) -> Any:
        """Recursively resolves #/components/schemas/<Name> references within a schema."""
        if seen_refs is None:
            seen_refs = set()

        if isinstance(schema, dict):
            if "$ref" in schema:
                ref: str = schema["$ref"]
                # Guard against circular references
                if ref in seen_refs:
                    return {"type": "object", "description": f"Circular ref {ref}"}

                if ref.startswith("#/components/schemas/"):
                    component_name = ref.split("/")[-1]
                    if component_name in components_schemas:
                        target = copy.deepcopy(components_schemas[component_name])
                        new_seen = seen_refs | {ref}
                        # Merge any sibling keys (like description) with the resolved schema
                        resolved = OpenApiFetcher.dereference_schema(target, components_schemas, new_seen)
                        for k, v in schema.items():
                            if k != "$ref" and k not in resolved:
                                resolved[k] = v
                        return resolved

            return {
                k: OpenApiFetcher.dereference_schema(v, components_schemas, seen_refs)
                for k, v in schema.items()
            }
        elif isinstance(schema, list):
            return [
                OpenApiFetcher.dereference_schema(item, components_schemas, seen_refs)
                for item in schema
            ]
        return schema

    @staticmethod
    def extract_components_schemas(spec: dict[str, Any]) -> dict[str, Any]:
        """Extracts components.schemas dictionary from OpenAPI specification."""
        components = spec.get("components", {})
        return components.get("schemas", {})
