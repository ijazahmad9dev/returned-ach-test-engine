"""Tests for Phase 2: API Inspection & Contract Discovery Layer."""

import pytest
import httpx

from test_engine.config import EngineConfig
from test_engine.discovery.contract_analyzer import ContractAnalyzer
from test_engine.discovery.openapi_fetcher import OpenApiFetcher
from test_engine.discovery.resolver import TargetResolver


# Sample OpenAPI 3.1 specification for unit testing
SAMPLE_OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "AgentOS runtime",
        "version": "1.0.0",
    },
    "paths": {
        "/api/v1/health": {
            "get": {
                "summary": "Health check",
                "tags": ["runtime"],
                "responses": {
                    "200": {
                        "description": "Healthy",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Health"}
                            }
                        },
                    }
                },
            }
        },
        "/api/v1/triggers/returned-ach": {
            "post": {
                "summary": "Trigger ACH Return workflow",
                "operationId": "trigger_returned_ach",
                "tags": ["runtime", "triggers"],
                "parameters": [
                    {
                        "name": "X-User-Id",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Trigger"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TriggerAccepted"}
                            }
                        },
                    },
                    "422": {
                        "description": "Validation Error",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                },
            }
        },
        "/api/v1/cases/{case_id}": {
            "get": {
                "summary": "Get Case",
                "tags": ["cases"],
                "parameters": [
                    {
                        "name": "case_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Case found"},
                    "404": {"description": "Not found"},
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Health": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
            "TriggerAccepted": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "created": {"type": "boolean"},
                    "reopened": {"type": "boolean"},
                },
                "required": ["case_id", "created", "reopened"],
            },
            "ErrorEnvelope": {
                "type": "object",
                "properties": {
                    "error": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "fields": {"type": "array"},
                        },
                        "required": ["code", "message"],
                    }
                },
            },
            "Trigger": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "tenant_id",
                    "original_trace_number",
                    "return_reason_code",
                    "amount_minor",
                    "currency",
                ],
                "properties": {
                    "tenant_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "original_trace_number": {
                        "type": "string",
                        "pattern": r"^[A-Za-z0-9\-]{6,64}$",
                    },
                    "return_reason_code": {
                        "type": "string",
                        "pattern": r"(?i)^R\d{2}$",
                    },
                    "amount_minor": {"type": "integer", "minimum": 0},
                    "currency": {"type": "string", "pattern": r"(?i)^[A-Z]{3}$"},
                    "scenario": {"type": "string", "nullable": True},
                },
            },
        }
    },
}


def test_resolver_parse_target() -> None:
    config = EngineConfig(target_url="http://localhost:8000")
    resolver = TargetResolver(config)

    base, is_single, path = resolver.parse_target("http://localhost:8000")
    assert base == "http://localhost:8000"
    assert not is_single
    assert path is None

    base, is_single, path = resolver.parse_target("http://localhost:8000/api/v1/triggers/returned-ach")
    assert base == "http://localhost:8000"
    assert is_single
    assert path == "/api/v1/triggers/returned-ach"


@pytest.mark.asyncio
async def test_resolver_mocked_network() -> None:
    # Use httpx.MockTransport to test TargetResolver network probe logic
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        elif request.url.path == "/openapi.json":
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json=SAMPLE_OPENAPI_SPEC,
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        config = EngineConfig(target_url="http://testserver:8000")
        resolver = TargetResolver(config)
        resolution = await resolver.resolve(client=client)

        assert resolution.is_reachable
        assert resolution.health_ok
        assert resolution.health_data == {"status": "ok"}
        assert resolution.openapi_url == "http://testserver:8000/openapi.json"


def test_dereference_schema() -> None:
    components = SAMPLE_OPENAPI_SPEC["components"]["schemas"]
    raw = {"$ref": "#/components/schemas/Trigger"}
    resolved = OpenApiFetcher.dereference_schema(raw, components)

    assert resolved["type"] == "object"
    assert "properties" in resolved
    assert "original_trace_number" in resolved["properties"]
    assert resolved["properties"]["original_trace_number"]["pattern"] == r"^[A-Za-z0-9\-]{6,64}$"


def test_contract_analyzer_full_spec() -> None:
    analyzer = ContractAnalyzer()
    contract = analyzer.analyze(
        spec=SAMPLE_OPENAPI_SPEC,
        base_url="http://localhost:8000",
        target_url="http://localhost:8000",
        health_ok=True,
    )

    assert contract.title == "AgentOS runtime"
    assert contract.version == "1.0.0"
    assert len(contract.endpoints) == 3
    assert not contract.is_single_endpoint_mode

    # Find trigger endpoint
    trigger_ep = contract.find_endpoint("/api/v1/triggers/returned-ach", "POST")
    assert trigger_ep is not None
    assert trigger_ep.summary == "Trigger ACH Return workflow"
    assert trigger_ep.operation_id == "trigger_returned_ach"
    assert trigger_ep.requires_auth is True  # has X-User-Id header param

    # Verify field validation rules
    rules = {r.field_name: r for r in trigger_ep.field_rules}
    assert "original_trace_number" in rules
    assert rules["original_trace_number"].required is True
    assert rules["original_trace_number"].pattern == r"^[A-Za-z0-9\-]{6,64}$"

    assert "amount_minor" in rules
    assert rules["amount_minor"].required is True
    assert rules["amount_minor"].field_type == "integer"
    assert rules["amount_minor"].minimum == 0

    assert "return_reason_code" in rules
    assert rules["return_reason_code"].pattern == r"(?i)^R\d{2}$"


def test_contract_analyzer_single_endpoint_mode() -> None:
    analyzer = ContractAnalyzer()
    contract = analyzer.analyze(
        spec=SAMPLE_OPENAPI_SPEC,
        base_url="http://localhost:8000",
        target_url="http://localhost:8000/api/v1/triggers/returned-ach",
        is_single_endpoint_mode=True,
        single_path="/api/v1/triggers/returned-ach",
        health_ok=True,
    )

    assert contract.is_single_endpoint_mode
    # Only 1 endpoint matching /api/v1/triggers/returned-ach should be retained
    assert len(contract.endpoints) == 1
    assert contract.endpoints[0].path == "/api/v1/triggers/returned-ach"
    assert contract.endpoints[0].method == "POST"


def test_contract_analyzer_fallback() -> None:
    analyzer = ContractAnalyzer()
    fallback = analyzer.create_fallback_contract(
        base_url="http://localhost:8000",
        target_url="http://localhost:8000/api/v1/triggers/returned-ach",
        endpoint_path="/api/v1/triggers/returned-ach",
        health_ok=True,
    )
    assert fallback.is_single_endpoint_mode
    assert len(fallback.endpoints) == 1
    assert fallback.endpoints[0].method == "POST"
    assert fallback.endpoints[0].path == "/api/v1/triggers/returned-ach"
