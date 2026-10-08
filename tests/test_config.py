"""Tests for test_engine.config."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from test_engine.config import EngineConfig, ExecutionMode, TestSuite


def test_default_config() -> None:
    config = EngineConfig()
    assert config.target_url == "http://localhost:8000"
    assert config.base_url == "http://localhost:8000"
    assert not config.is_specific_endpoint
    assert config.specific_endpoint_path is None
    assert config.openapi_url == "http://localhost:8000/openapi.json"
    assert config.health_url == "http://localhost:8000/api/v1/health"
    assert config.execution_mode == ExecutionMode.MOCK
    assert config.timeout_seconds == 15.0
    assert config.max_concurrency == 5


def test_specific_endpoint_detection() -> None:
    endpoint_url = "http://localhost:8000/api/v1/triggers/returned-ach"
    config = EngineConfig(target_url=endpoint_url)
    assert config.target_url == endpoint_url
    assert config.base_url == "http://localhost:8000"
    assert config.is_specific_endpoint
    assert config.specific_endpoint_path == "/api/v1/triggers/returned-ach"
    assert config.openapi_url == "http://localhost:8000/openapi.json"


def test_invalid_target_url() -> None:
    with pytest.raises(ValidationError):
        EngineConfig(target_url="invalid-url-without-scheme")

    with pytest.raises(ValidationError):
        EngineConfig(target_url="ftp://localhost:8000")


def test_yaml_config_loading() -> None:
    yaml_content = """
target_url: "https://api.staging.internal:8443"
execution_mode: "real"
timeout_seconds: 30.0
max_concurrency: 10
suites:
  - "health"
  - "schema"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        temp_path = f.name

    try:
        config = EngineConfig.from_yaml(temp_path, timeout_seconds=45.0)
        assert config.target_url == "https://api.staging.internal:8443"
        assert config.base_url == "https://api.staging.internal:8443"
        assert config.execution_mode == ExecutionMode.REAL
        assert config.timeout_seconds == 45.0  # override took precedence
        assert config.max_concurrency == 10
        assert config.suites == ["health", "schema"]
    finally:
        Path(temp_path).unlink(missing_ok=True)
