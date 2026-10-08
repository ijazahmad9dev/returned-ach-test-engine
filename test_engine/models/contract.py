"""Data models representing API contracts, endpoints, schemas, and validation rules."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ParameterSpec(BaseModel):
    """Specification for an API parameter (query, path, header, cookie)."""

    name: str
    location: Literal["path", "query", "header", "cookie"]
    required: bool = False
    schema_def: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class FieldValidationRule(BaseModel):
    """Extracted schema constraints for a specific request or body field."""

    field_name: str
    field_type: str = "string"
    format: str | None = None
    required: bool = False
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum_values: list[Any] | None = None
    description: str = ""
    is_strict_extra: bool = False


class EndpointContract(BaseModel):
    """Detailed contract specification for a single API endpoint operation."""

    path: str
    method: str = "GET"
    operation_id: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    parameters: list[ParameterSpec] = Field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    response_schemas: dict[str, dict[str, Any]] = Field(default_factory=dict)
    field_rules: list[FieldValidationRule] = Field(default_factory=list)
    requires_auth: bool = False
    required_headers: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """Unique key e.g. 'POST /api/v1/triggers/returned-ach'."""
        return f"{self.method.upper()} {self.path}"

    @property
    def path_param_names(self) -> list[str]:
        return [p.name for p in self.parameters if p.location == "path"]

    @property
    def query_param_names(self) -> list[str]:
        return [p.name for p in self.parameters if p.location == "query"]

    @property
    def header_param_names(self) -> list[str]:
        return [p.name for p in self.parameters if p.location == "header"]


class ApiContract(BaseModel):
    """Aggregated contract representing the discovered API surface."""

    base_url: str
    target_url: str
    title: str = "Target API"
    version: str = "1.0.0"
    is_single_endpoint_mode: bool = False
    health_ok: bool = False
    health_details: dict[str, Any] = Field(default_factory=dict)
    endpoints: list[EndpointContract] = Field(default_factory=list)
    components_schemas: dict[str, Any] = Field(default_factory=dict)

    def find_endpoint(self, path: str, method: str = "GET") -> EndpointContract | None:
        """Find a specific endpoint by path and HTTP method."""
        method_upper = method.upper()
        for ep in self.endpoints:
            if ep.path == path and ep.method.upper() == method_upper:
                return ep
        return None

    def endpoints_for_path(self, path: str) -> list[EndpointContract]:
        """Find all HTTP methods available on a specific path."""
        return [ep for ep in self.endpoints if ep.path == path]

    def filter_by_tag(self, tag: str) -> list[EndpointContract]:
        """Filter endpoints matching an OpenAPI tag."""
        return [ep for ep in self.endpoints if tag.lower() in [t.lower() for t in ep.tags]]

    @property
    def endpoint_paths(self) -> list[str]:
        return sorted({ep.path for ep in self.endpoints})
