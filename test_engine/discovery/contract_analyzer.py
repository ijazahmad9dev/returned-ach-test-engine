"""Contract and Route Analyzer for OpenAPI specifications."""

from __future__ import annotations

from typing import Any

from test_engine.discovery.openapi_fetcher import OpenApiFetcher
from test_engine.logger import get_logger
from test_engine.models.contract import (
    ApiContract,
    EndpointContract,
    FieldValidationRule,
    ParameterSpec,
)

logger = get_logger("discovery.contract_analyzer")

# HTTP methods analyzed
SUPPORTED_METHODS = {"get", "post", "put", "delete", "patch", "options"}


class ContractAnalyzer:
    """Analyzes OpenAPI specifications, extracts parameter constraints, and builds ApiContract."""

    def __init__(self, openapi_fetcher: OpenApiFetcher | None = None) -> None:
        self.fetcher = openapi_fetcher or OpenApiFetcher()

    def analyze(
        self,
        spec: dict[str, Any],
        base_url: str,
        target_url: str,
        is_single_endpoint_mode: bool = False,
        single_path: str | None = None,
        health_ok: bool = False,
        health_details: dict[str, Any] | None = None,
    ) -> ApiContract:
        """Parses an OpenAPI spec into a full ApiContract model."""
        info = spec.get("info", {})
        title = info.get("title", "Target API")
        version = info.get("version", "1.0.0")
        components_schemas = self.fetcher.extract_components_schemas(spec)

        endpoints: list[EndpointContract] = []
        paths: dict[str, Any] = spec.get("paths", {})

        for path, path_item in paths.items():
            # If in single endpoint mode, only analyze the targeted path
            if is_single_endpoint_mode and single_path:
                if path.rstrip("/") != single_path.rstrip("/"):
                    continue

            common_params = path_item.get("parameters", [])

            for method, operation in path_item.items():
                if method.lower() not in SUPPORTED_METHODS:
                    continue

                endpoint = self._parse_endpoint(
                    path=path,
                    method=method.upper(),
                    operation=operation,
                    common_params=common_params,
                    components_schemas=components_schemas,
                )
                endpoints.append(endpoint)

        return ApiContract(
            base_url=base_url,
            target_url=target_url,
            title=title,
            version=version,
            is_single_endpoint_mode=is_single_endpoint_mode,
            health_ok=health_ok,
            health_details=health_details or {},
            endpoints=endpoints,
            components_schemas=components_schemas,
        )

    def _parse_endpoint(
        self,
        path: str,
        method: str,
        operation: dict[str, Any],
        common_params: list[dict[str, Any]],
        components_schemas: dict[str, Any],
    ) -> EndpointContract:
        """Parses a single operation into an EndpointContract."""
        summary = operation.get("summary", "")
        operation_id = operation.get("operationId", "")
        tags = operation.get("tags", [])

        # Parse parameters
        all_params = list(common_params) + list(operation.get("parameters", []))
        parameters: list[ParameterSpec] = []
        requires_auth = False
        required_headers: list[str] = []

        for p in all_params:
            if "$ref" in p:
                p = OpenApiFetcher.dereference_schema(p, components_schemas)

            param_name = p.get("name", "")
            param_in = p.get("in", "query")
            param_required = p.get("required", False)
            schema_def = p.get("schema", {})

            if param_in == "header":
                if param_name.lower() in ("x-user-id", "authorization"):
                    requires_auth = True
                if param_required:
                    required_headers.append(param_name)

            parameters.append(
                ParameterSpec(
                    name=param_name,
                    location=param_in,
                    required=param_required,
                    schema_def=schema_def,
                    description=p.get("description", ""),
                )
            )

        # Parse request body schema
        request_schema = None
        field_rules: list[FieldValidationRule] = []

        request_body = operation.get("requestBody", {})
        if "$ref" in request_body:
            request_body = OpenApiFetcher.dereference_schema(request_body, components_schemas)

        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        raw_schema = json_content.get("schema")

        if raw_schema:
            request_schema = OpenApiFetcher.dereference_schema(raw_schema, components_schemas)
            field_rules = self._extract_field_rules(request_schema)

        # Parse responses
        response_schemas: dict[str, dict[str, Any]] = {}
        for status_code, resp_def in operation.get("responses", {}).items():
            if "$ref" in resp_def:
                resp_def = OpenApiFetcher.dereference_schema(resp_def, components_schemas)
            resp_content = resp_def.get("content", {}).get("application/json", {})
            schema = resp_content.get("schema")
            if schema:
                response_schemas[str(status_code)] = OpenApiFetcher.dereference_schema(
                    schema, components_schemas
                )
            else:
                response_schemas[str(status_code)] = {}

        return EndpointContract(
            path=path,
            method=method,
            operation_id=operation_id,
            summary=summary,
            tags=tags,
            parameters=parameters,
            request_schema=request_schema,
            response_schemas=response_schemas,
            field_rules=field_rules,
            requires_auth=requires_auth,
            required_headers=required_headers,
        )

    def _extract_field_rules(self, schema: dict[str, Any]) -> list[FieldValidationRule]:
        """Extracts validation rules (required, regex pattern, bounds, types) from request schema."""
        rules: list[FieldValidationRule] = []
        if not isinstance(schema, dict):
            return rules

        properties = schema.get("properties", {})
        required_fields = set(schema.get("required", []))
        strict_extra = schema.get("additionalProperties") is False

        for field_name, field_def in properties.items():
            if not isinstance(field_def, dict):
                continue

            field_type = field_def.get("type")
            if not field_type and "anyOf" in field_def:
                for sub in field_def["anyOf"]:
                    if isinstance(sub, dict) and sub.get("type") and sub.get("type") != "null":
                        field_type = sub.get("type")
                        break
            if not field_type:
                field_type = "string"

            rule = FieldValidationRule(
                field_name=field_name,
                field_type=str(field_type),
                format=field_def.get("format"),
                required=field_name in required_fields,
                min_length=field_def.get("minLength"),
                max_length=field_def.get("maxLength"),
                pattern=field_def.get("pattern"),
                minimum=field_def.get("minimum"),
                maximum=field_def.get("maximum"),
                enum_values=field_def.get("enum"),
                description=field_def.get("description", ""),
                is_strict_extra=strict_extra,
            )
            rules.append(rule)

        return rules

    def create_fallback_contract(
        self,
        base_url: str,
        target_url: str,
        endpoint_path: str,
        health_ok: bool = False,
    ) -> ApiContract:
        """Constructs a minimal contract for an endpoint when OpenAPI spec is not available."""
        endpoint = EndpointContract(
            path=endpoint_path,
            method="POST" if "trigger" in endpoint_path else "GET",
            summary=f"Discovered endpoint at {endpoint_path}",
            tags=["fallback"],
        )
        return ApiContract(
            base_url=base_url,
            target_url=target_url,
            title="Inferred API Contract",
            version="1.0.0",
            is_single_endpoint_mode=True,
            health_ok=health_ok,
            endpoints=[endpoint],
        )
