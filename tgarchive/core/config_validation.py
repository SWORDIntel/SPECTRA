"""
SPECTRA Configuration Validation Module
========================================
Comprehensive configuration validation with JSON schema support and input sanitization.

Features:
- JSON schema validation for configuration files
- Input sanitization for entity names, paths, and parameters
- Type checking and range validation
- Security validation (permissions, paths, credentials)
- Detailed error reporting
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# JSON Schema for SPECTRA configuration
CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SPECTRA Configuration Schema",
    "type": "object",
    "required": ["accounts"],
    "properties": {
        "api_id": {
            "type": "integer",
            "minimum": 1,
            "maximum": 999999999,
            "description": "Legacy single API ID (deprecated, use accounts)"
        },
        "api_hash": {
            "type": "string",
            "minLength": 32,
            "maxLength": 32,
            "pattern": "^[a-f0-9]{32}$",
            "description": "Legacy single API hash (deprecated, use accounts)"
        },
        "accounts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["api_id", "api_hash", "session_name"],
                "properties": {
                    "api_id": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 999999999
                    },
                    "api_hash": {
                        "type": "string",
                        "minLength": 32,
                        "maxLength": 32,
                        "pattern": "^[a-f0-9]{32}$"
                    },
                    "session_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 255,
                        "pattern": "^[a-zA-Z0-9_.-]+$"
                    },
                    "phone_number": {
                        "type": "string",
                        "pattern": "^\\+?[0-9]{10,15}$"
                    },
                    "password": {
                        "type": "string"
                    }
                }
            }
        },
        "proxy": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255
                },
                "user": {
                    "type": "string"
                },
                "password": {
                    "type": "string"
                },
                "ports": {
                    "type": "array",
                    "items": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 65535
                    }
                }
            }
        },
        "entity": {
            "type": "string",
            "maxLength": 500
        },
        "db_path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096
        },
        "media_dir": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096
        },
        "download_media": {
            "type": "boolean"
        },
        "download_avatars": {
            "type": "boolean"
        },
        "media_mime_whitelist": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "batch": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10000
        },
        "sleep_between_batches": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 3600.0
        },
        "use_takeout": {
            "type": "boolean"
        },
        "avatar_size": {
            "type": "integer",
            "enum": [64, 128, 256, 512]
        },
        "collect_usernames": {
            "type": "boolean"
        },
        "sidecar_metadata": {
            "type": "boolean"
        },
        "archive_topics": {
            "type": "boolean"
        },
        "default_forwarding_destination_id": {
            "type": ["integer", "null"]
        },
        "forwarding": {
            "type": "object",
            "properties": {
                "enable_deduplication": {"type": "boolean"},
                "secondary_unique_destination": {"type": ["integer", "null"]},
                "always_prepend_origin_info": {"type": "boolean"}
            }
        },
        "deduplication": {
            "type": "object",
            "properties": {
                "enable_near_duplicates": {"type": "boolean"},
                "fuzzy_hash_similarity_threshold": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100
                },
                "perceptual_hash_distance_threshold": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 64
                },
                "forward_with_attribution": {"type": "boolean"}
            }
        },
        "cloud": {
            "type": "object",
            "properties": {
                "auto_invite_accounts": {"type": "boolean"},
                "invitation_delays": {
                    "type": "object",
                    "properties": {
                        "min_seconds": {"type": "integer", "minimum": 0},
                        "max_seconds": {"type": "integer", "minimum": 0},
                        "variance": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                    }
                }
            }
        },
        "vps": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "host": {"type": "string"},
                "port": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 65535
                },
                "username": {"type": "string"},
                "key_path": {"type": "string"},
                "remote_base_path": {"type": "string"}
            }
        },
        "grouping": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["none", "time", "content", "smart"]
                },
                "time_window_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 86400
                }
            }
        }
    }
}


@dataclass
class ValidationError:
    """Validation error details."""
    field: str
    message: str
    severity: str = "error"  # error, warning
    value: Optional[Any] = None

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


class ConfigValidator:
    """
    Validates SPECTRA configuration against schema and security requirements.
    """

    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []

    def validate_config(self, config_data: Dict[str, Any]) -> tuple[bool, List[ValidationError]]:
        """
        Validate entire configuration.

        Returns:
            (is_valid: bool, errors: List[ValidationError])
        """
        self.errors.clear()
        self.warnings.clear()

        # Basic schema validation
        self._validate_schema(config_data)

        # Security validation
        self._validate_security(config_data)

        # Business logic validation
        self._validate_business_logic(config_data)

        # Combine errors and warnings
        all_issues = self.errors + self.warnings

        return len(self.errors) == 0, all_issues

    def _validate_schema(self, config_data: Dict[str, Any]) -> None:
        """Validate configuration against JSON schema."""
        try:
            # Manual validation (jsonschema library not required)
            self._validate_dict_against_schema(config_data, CONFIG_SCHEMA)

        except Exception as e:
            self.errors.append(ValidationError(
                field="schema",
                message=f"Schema validation error: {e}",
                severity="error"
            ))

    def _validate_dict_against_schema(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
        path: str = ""
    ) -> None:
        """Recursively validate dict against schema (simplified)."""

        # Check required fields
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                self.errors.append(ValidationError(
                    field=f"{path}.{field}" if path else field,
                    message="Required field missing",
                    severity="error"
                ))

        # Validate properties
        properties = schema.get("properties", {})
        for field, field_schema in properties.items():
            full_path = f"{path}.{field}" if path else field

            if field not in data:
                continue

            value = data[field]
            self._validate_value(value, field_schema, full_path)

    def _validate_value(self, value: Any, schema: Dict[str, Any], path: str) -> None:
        """Validate a single value against its schema."""

        # Type validation
        expected_type = schema.get("type")
        if expected_type:
            if isinstance(expected_type, list):
                # Multiple allowed types (e.g., ["integer", "null"])
                valid_type = False
                for type_option in expected_type:
                    if self._check_type(value, type_option):
                        valid_type = True
                        break
                if not valid_type:
                    self.errors.append(ValidationError(
                        field=path,
                        message=f"Invalid type. Expected one of {expected_type}, got {type(value).__name__}",
                        value=value
                    ))
            else:
                # Single type
                if not self._check_type(value, expected_type):
                    self.errors.append(ValidationError(
                        field=path,
                        message=f"Invalid type. Expected {expected_type}, got {type(value).__name__}",
                        value=value
                    ))

        # String validations
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"String too short (min: {schema['minLength']})",
                    value=value
                ))
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"String too long (max: {schema['maxLength']})",
                    value=value
                ))
            if "pattern" in schema:
                if not re.match(schema["pattern"], value):
                    self.errors.append(ValidationError(
                        field=path,
                        message=f"String doesn't match pattern {schema['pattern']}",
                        value=value
                    ))

        # Number validations
        if isinstance(value, (int, float)):
            if "minimum" in schema and value < schema["minimum"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"Value below minimum ({schema['minimum']})",
                    value=value
                ))
            if "maximum" in schema and value > schema["maximum"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"Value above maximum ({schema['maximum']})",
                    value=value
                ))
            if "enum" in schema and value not in schema["enum"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"Value not in allowed values: {schema['enum']}",
                    value=value
                ))

        # Array validations
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                self.errors.append(ValidationError(
                    field=path,
                    message=f"Array too short (min items: {schema['minItems']})",
                    value=len(value)
                ))
            if "items" in schema:
                for idx, item in enumerate(value):
                    self._validate_value(item, schema["items"], f"{path}[{idx}]")

        # Object validations
        if isinstance(value, dict) and "properties" in schema:
            self._validate_dict_against_schema(value, schema, path)

    @staticmethod
    def _check_type(value: Any, type_name: str) -> bool:
        """Check if value matches type name."""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }

        expected_type = type_map.get(type_name)
        if not expected_type:
            return True  # Unknown type, skip validation

        return isinstance(value, expected_type)

    def _validate_security(self, config_data: Dict[str, Any]) -> None:
        """Validate security aspects of configuration."""

        # Check if credentials are using defaults
        accounts = config_data.get("accounts", [])
        for idx, account in enumerate(accounts):
            api_id = account.get("api_id")
            api_hash = account.get("api_hash")

            if api_id == 123456:
                self.warnings.append(ValidationError(
                    field=f"accounts[{idx}].api_id",
                    message="Using default API ID - please set real credentials",
                    severity="warning"
                ))

            if api_hash and api_hash.startswith("0123456789abcdef"):
                self.warnings.append(ValidationError(
                    field=f"accounts[{idx}].api_hash",
                    message="Using default API hash - please set real credentials",
                    severity="warning"
                ))

        # Check proxy credentials
        proxy = config_data.get("proxy", {})
        if proxy.get("password") == "PROXY_PASS":
            self.warnings.append(ValidationError(
                field="proxy.password",
                message="Using default proxy password",
                severity="warning"
            ))

        # Check file paths for security
        for path_field in ["db_path", "media_dir"]:
            if path_field in config_data:
                path_value = config_data[path_field]
                if not self._is_safe_path(path_value):
                    self.errors.append(ValidationError(
                        field=path_field,
                        message="Path contains potentially unsafe characters",
                        value=path_value
                    ))

    def _validate_business_logic(self, config_data: Dict[str, Any]) -> None:
        """Validate business logic rules."""

        # Validate batch size is reasonable
        batch = config_data.get("batch", 500)
        if batch > 5000:
            self.warnings.append(ValidationError(
                field="batch",
                message="Large batch size may cause memory issues",
                severity="warning",
                value=batch
            ))

        # Validate cloud invitation delays
        cloud = config_data.get("cloud", {})
        delays = cloud.get("invitation_delays", {})
        min_sec = delays.get("min_seconds", 0)
        max_sec = delays.get("max_seconds", 0)

        if min_sec > max_sec:
            self.errors.append(ValidationError(
                field="cloud.invitation_delays",
                message="min_seconds cannot be greater than max_seconds",
                value={"min": min_sec, "max": max_sec}
            ))

        # Validate VPS configuration if enabled
        vps = config_data.get("vps", {})
        if vps.get("enabled"):
            required_vps_fields = ["host", "username", "key_path"]
            for field in required_vps_fields:
                if not vps.get(field):
                    self.errors.append(ValidationError(
                        field=f"vps.{field}",
                        message=f"VPS enabled but {field} not configured"
                    ))

    @staticmethod
    def _is_safe_path(path_str: str) -> bool:
        """Check if path is safe (no directory traversal, etc.)."""
        # Check for directory traversal
        if ".." in path_str:
            return False

        # Check for absolute paths that might be dangerous
        dangerous_paths = ["/etc/", "/sys/", "/proc/", "/dev/"]
        for dangerous in dangerous_paths:
            if path_str.startswith(dangerous):
                return False

        return True


class InputSanitizer:
    """
    Sanitizes and validates user inputs to prevent injection attacks and errors.

    TEMPEST Security: Prevents data leakage through malformed inputs.
    """

    # Allowed patterns for various input types
    ENTITY_PATTERN = re.compile(r'^[@a-zA-Z0-9_.-]{1,500}$')
    CHANNEL_ID_PATTERN = re.compile(r'^-?\d{1,20}$')
    SESSION_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_.-]{1,255}$')
    PHONE_PATTERN = re.compile(r'^\+?[0-9]{10,15}$')

    @classmethod
    def sanitize_entity_name(cls, entity: str) -> tuple[bool, str, Optional[str]]:
        """
        Sanitize and validate entity name (channel username or ID).

        Returns:
            (is_valid: bool, sanitized_value: str, error_message: Optional[str])
        """
        if not entity:
            return False, "", "Entity name is empty"

        # Strip whitespace
        entity = entity.strip()

        # Check if it's a numeric ID
        if entity.lstrip('-').isdigit():
            if cls.CHANNEL_ID_PATTERN.match(entity):
                return True, entity, None
            else:
                return False, entity, "Invalid channel ID format"

        # Check if it's a username
        if cls.ENTITY_PATTERN.match(entity):
            # Ensure it starts with @ if it's a username
            if not entity.startswith('@') and not entity.lstrip('-').isdigit():
                entity = '@' + entity
            return True, entity, None

        return False, entity, "Entity name contains invalid characters"

    @classmethod
    def sanitize_session_name(cls, session_name: str) -> tuple[bool, str, Optional[str]]:
        """Sanitize and validate session name."""
        if not session_name:
            return False, "", "Session name is empty"

        session_name = session_name.strip()

        if cls.SESSION_NAME_PATTERN.match(session_name):
            return True, session_name, None

        return False, session_name, "Session name contains invalid characters"

    @classmethod
    def sanitize_phone_number(cls, phone: str) -> tuple[bool, str, Optional[str]]:
        """Sanitize and validate phone number."""
        if not phone:
            return False, "", "Phone number is empty"

        # Remove spaces and dashes
        phone = re.sub(r'[\s-]', '', phone)

        if cls.PHONE_PATTERN.match(phone):
            # Ensure it starts with +
            if not phone.startswith('+'):
                phone = '+' + phone
            return True, phone, None

        return False, phone, "Invalid phone number format"

    @classmethod
    def sanitize_path(cls, path_str: str, must_be_relative: bool = True) -> tuple[bool, str, Optional[str]]:
        """
        Sanitize and validate file system path.

        Args:
            path_str: Path string to sanitize
            must_be_relative: If True, reject absolute paths

        Returns:
            (is_valid: bool, sanitized_path: str, error_message: Optional[str])
        """
        if not path_str:
            return False, "", "Path is empty"

        path_str = path_str.strip()

        # Check for directory traversal
        if ".." in path_str:
            return False, path_str, "Path contains directory traversal (..)"

        # Check for null bytes
        if "\x00" in path_str:
            return False, path_str, "Path contains null bytes"

        # Check if absolute when it shouldn't be
        if must_be_relative and Path(path_str).is_absolute():
            return False, path_str, "Absolute paths not allowed in this context"

        # Normalize path
        try:
            normalized = str(Path(path_str))
            return True, normalized, None
        except Exception as e:
            return False, path_str, f"Invalid path: {e}"

    @classmethod
    def sanitize_url(cls, url: str) -> tuple[bool, str, Optional[str]]:
        """Sanitize and validate URL."""
        if not url:
            return False, "", "URL is empty"

        url = url.strip()

        try:
            parsed = urlparse(url)

            # Check for valid scheme
            if parsed.scheme not in ('http', 'https', 'socks5'):
                return False, url, f"Invalid URL scheme: {parsed.scheme}"

            # Check for host
            if not parsed.netloc:
                return False, url, "URL missing host"

            return True, url, None

        except Exception as e:
            return False, url, f"Invalid URL: {e}"


__all__ = [
    "CONFIG_SCHEMA",
    "ValidationError",
    "ConfigValidator",
    "InputSanitizer",
]
