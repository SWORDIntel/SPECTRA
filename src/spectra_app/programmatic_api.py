"""OpenAPI-oriented machine interface for SPECTRA."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict


class SpectraProgrammaticAPI:
    """Expose standard REST resources and an OpenAPI 3.1 description."""

    def __init__(self, launcher):
        self.launcher = launcher

    def get_context_snapshot(self) -> Dict[str, Any]:
        return {
            "system": self.launcher.get_system_status(),
            "components": self.launcher.get_component_status(),
            "security": self.get_security_resource(),
            "documentation": {
                "readme_preview": self.get_readme_resource(2000)["content"],
            },
        }

    def get_security_resource(self) -> Dict[str, Any]:
        return {
            "warnings": self.launcher._get_security_warnings(),
            "local_only": self.launcher.local_only,
            "host": self.launcher.config.host,
            "port": self.launcher.available_port or self.launcher.config.port,
            "security_level": "HIGH" if self.launcher.local_only else "LOW",
            "api_key_required": self.launcher.api_key_enabled,
        }

    def get_readme_resource(self, max_chars: int = 4000) -> Dict[str, Any]:
        raw = self.launcher._get_readme_content()
        return {
            "content": raw[:max_chars],
            "truncated": len(raw) > max_chars,
            "max_chars": max_chars,
        }

    def get_openapi_spec(self) -> Dict[str, Any]:
        server_url = f"http://{self.launcher.config.host}:{self.launcher.available_port or self.launcher.config.port}"
        security_requirement = [{"ApiKeyHeader": []}, {"ApiKeyQuery": []}] if self.launcher.api_key_enabled else []
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "SPECTRA Local Control API",
                "version": "1.0.0",
                "summary": "Standard REST/OpenAPI control surface for the local SPECTRA interface.",
                "description": (
                    "This API exposes local system status, security posture, documentation context, "
                    "and selected control operations in a standard OpenAPI format suitable for AI clients."
                ),
            },
            "servers": [{"url": server_url}],
            "security": security_requirement,
            "components": {
                "securitySchemes": {
                    "ApiKeyHeader": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-API-Key",
                    },
                    "ApiKeyQuery": {
                        "type": "apiKey",
                        "in": "query",
                        "name": "api_key",
                    },
                },
                "schemas": {
                    "RestartComponentRequest": {
                        "type": "object",
                        "properties": {
                            "component_name": {"type": "string"},
                        },
                        "required": ["component_name"],
                        "additionalProperties": False,
                    },
                    "ReadmeResponse": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "truncated": {"type": "boolean"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["content", "truncated", "max_chars"],
                    },
                },
            },
            "paths": {
                "/api/system/status": {
                    "get": {
                        "operationId": "getSystemStatus",
                        "summary": "Get system status",
                        "responses": {"200": {"description": "System status JSON"}},
                    }
                },
                "/api/components/health": {
                    "get": {
                        "operationId": "getComponentHealth",
                        "summary": "Get component health",
                        "responses": {"200": {"description": "Component health JSON"}},
                    }
                },
                "/api/security/warnings": {
                    "get": {
                        "operationId": "getSecurityWarnings",
                        "summary": "Get security posture",
                        "responses": {"200": {"description": "Security warnings JSON"}},
                    }
                },
                "/api/v1/context": {
                    "get": {
                        "operationId": "getContextSnapshot",
                        "summary": "Get structured system context",
                        "responses": {"200": {"description": "Context snapshot JSON"}},
                    }
                },
                "/api/v1/readme": {
                    "get": {
                        "operationId": "getReadmeExcerpt",
                        "summary": "Get a README excerpt",
                        "parameters": [
                            {
                                "name": "max_chars",
                                "in": "query",
                                "schema": {"type": "integer", "minimum": 200, "maximum": 12000, "default": 4000},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "README excerpt",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/ReadmeResponse"}
                                    }
                                },
                            }
                        },
                    }
                },
                "/api/components/{component_name}/restart": {
                    "post": {
                        "operationId": "restartComponent",
                        "summary": "Restart a component",
                        "parameters": [
                            {
                                "name": "component_name",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "Restart result JSON"}},
                    }
                },
            },
        }

    def _serialize(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {k: self._serialize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._serialize(v) for v in value]
        return value
