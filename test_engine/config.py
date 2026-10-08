"""Configuration management for Return ACH Test Engine."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class TestSuite(str, Enum):
    __test__ = False
    HEALTH = "health"
    SCHEMA = "schema"
    ACH_DOMAIN = "ach_domain"
    SECURITY = "security"
    CONNECTORS = "connectors"
    E2E = "e2e"
    ALL = "all"


class EngineConfig(BaseSettings):
    """Central configuration for Return ACH Test Engine."""

    model_config = SettingsConfigDict(
        env_prefix="ACH_TEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Target API settings
    target_url: str = Field(
        default="http://localhost:8000",
        description="Base backend URL or specific target endpoint",
    )
    openapi_path: str = Field(
        default="/openapi.json",
        description="Path to OpenAPI JSON specification",
    )
    health_path: str = Field(
        default="/api/v1/health",
        description="Path to health check endpoint",
    )

    # Connector & Execution mode
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.MOCK,
        description="Execution mode: mock or real upstream connectors",
    )
    suites: list[str] = Field(
        default_factory=lambda: [
            TestSuite.HEALTH.value,
            TestSuite.SCHEMA.value,
            TestSuite.ACH_DOMAIN.value,
            TestSuite.SECURITY.value,
            TestSuite.CONNECTORS.value,
        ],
        description="Test suites to execute",
    )

    # HTTP & Performance settings
    timeout_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=120.0,
        description="HTTP request timeout in seconds",
    )
    max_concurrency: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum concurrent HTTP requests",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Number of retries for transient HTTP errors",
    )
    retry_backoff_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        description="Initial backoff delay in seconds between retries",
    )

    # Reporting settings
    output_dir: Path = Field(
        default=Path("reports"),
        description="Directory where test artifacts and reports are saved",
    )
    report_formats: list[Literal["console", "json", "markdown", "html"]] = Field(
        default_factory=lambda: ["console", "json", "markdown", "html"],
        description="Generated report output formats",
    )

    # Authentication & Identity Headers
    auth_user_id: str = Field(
        default="usr_test_operator_01",
        description="Default user ID injected into X-User-Id header",
    )
    auth_role: str = Field(
        default="reviewer",
        description="Default user role for RBAC operations",
    )
    tenant_id: str = Field(
        default="tenant_qa_01",
        description="Default tenant ID for multi-tenant headers and bodies",
    )
    custom_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional custom HTTP headers injected into requests",
    )

    # Logging & Debugging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Application log verbosity level",
    )
    verbose: bool = Field(
        default=False,
        description="Whether to print verbose wire logs and traces",
    )

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            raise ValueError(f"target_url must start with http:// or https://: {v}")
        if not parsed.netloc:
            raise ValueError(f"target_url must contain a valid host: {v}")
        return v.rstrip("/")

    @property
    def base_url(self) -> str:
        """Derive base URL (scheme://netloc) from target_url."""
        parsed = urlparse(self.target_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def is_specific_endpoint(self) -> bool:
        """True if target_url contains an API endpoint path beyond root."""
        parsed = urlparse(self.target_url)
        path = parsed.path.rstrip("/")
        return bool(path and path != "/")

    @property
    def specific_endpoint_path(self) -> str | None:
        """Returns the specific endpoint path if target_url targets a single endpoint."""
        if not self.is_specific_endpoint:
            return None
        parsed = urlparse(self.target_url)
        return parsed.path

    @property
    def openapi_url(self) -> str:
        """Full URL to OpenAPI spec."""
        return f"{self.base_url}{self.openapi_path}"

    @property
    def health_url(self) -> str:
        """Full URL to health check."""
        return f"{self.base_url}{self.health_path}"

    @classmethod
    def from_yaml(cls, yaml_path: str | Path, **overrides: Any) -> EngineConfig:
        """Load configuration from a YAML file with optional keyword overrides."""
        path = Path(yaml_path)
        if not path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Merge YAML data with explicit overrides
        merged = {**data, **{k: v for k, v in overrides.items() if v is not None}}
        return cls(**merged)
