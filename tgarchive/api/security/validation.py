"""
Input Validation & Sanitization (CSNA 2.0 Compliance)
=======================================================

Prevents injection attacks, XSS, and invalid data.
"""

import re
import logging
from typing import Any, Dict, Optional, List
from html import escape as html_escape

logger = logging.getLogger(__name__)


# Regex patterns for validation
PATTERNS = {
    'username': r'^[a-zA-Z0-9_-]{3,32}$',
    'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
    'channel_id': r'^-?\d{1,20}$',
    'message_id': r'^\d{1,20}$',
    'url': r'^https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%.]+$',
    'date': r'^\d{4}-\d{2}-\d{2}$',
}

# List of dangerous HTML tags and attributes
DANGEROUS_TAGS = {'script', 'iframe', 'embed', 'object', 'form', 'input', 'button'}
DANGEROUS_ATTRS = {'onclick', 'onload', 'onerror', 'onmouseover', 'onkeydown', 'onchange'}


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def validate_input(
    value: Any,
    input_type: str,
    required: bool = True,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    pattern: Optional[str] = None
) -> Any:
    """
    Validate input based on type and constraints.

    Args:
        value: Input value to validate
        input_type: Type of input (string, int, email, username, etc.)
        required: Whether value is required
        min_length: Minimum string length
        max_length: Maximum string length
        pattern: Custom regex pattern

    Returns:
        Validated and sanitized value

    Raises:
        ValidationError: If validation fails
    """
    # Check required
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError("Value is required")
        return None

    # Type-specific validation
    if input_type == 'string':
        return _validate_string(value, min_length, max_length, pattern)

    elif input_type == 'int':
        return _validate_int(value, min_length, max_length)

    elif input_type == 'email':
        return _validate_email(value)

    elif input_type == 'username':
        return _validate_username(value)

    elif input_type == 'channel_id':
        return _validate_channel_id(value)

    elif input_type == 'message_id':
        return _validate_message_id(value)

    elif input_type == 'url':
        return _validate_url(value)

    elif input_type == 'date':
        return _validate_date(value)

    elif input_type == 'bool':
        return _validate_bool(value)

    elif input_type == 'list':
        return _validate_list(value)

    elif input_type == 'dict':
        return _validate_dict(value)

    else:
        raise ValidationError(f"Unknown input type: {input_type}")


def _validate_string(
    value: str,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    pattern: Optional[str] = None
) -> str:
    """Validate and sanitize string input."""
    if not isinstance(value, str):
        raise ValidationError("Value must be a string")

    value = value.strip()

    if min_length and len(value) < min_length:
        raise ValidationError(f"String too short (min: {min_length})")

    if max_length and len(value) > max_length:
        raise ValidationError(f"String too long (max: {max_length})")

    if pattern and not re.match(pattern, value):
        raise ValidationError(f"String does not match pattern: {pattern}")

    # Sanitize: remove control characters, limit whitespace
    value = ''.join(char for char in value if ord(char) >= 32 or char in '\n\t')
    value = re.sub(r'\s+', ' ', value)  # Normalize whitespace

    return value


def _validate_int(
    value: Any,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None
) -> int:
    """Validate integer input."""
    try:
        int_val = int(value)
    except (ValueError, TypeError):
        raise ValidationError("Value must be an integer")

    if min_val is not None and int_val < min_val:
        raise ValidationError(f"Value too small (min: {min_val})")

    if max_val is not None and int_val > max_val:
        raise ValidationError(f"Value too large (max: {max_val})")

    return int_val


def _validate_email(value: str) -> str:
    """Validate email address."""
    value = _validate_string(value, max_length=254)

    if not re.match(PATTERNS['email'], value):
        raise ValidationError("Invalid email address")

    return value.lower()


def _validate_username(value: str) -> str:
    """Validate username."""
    value = _validate_string(value)

    if not re.match(PATTERNS['username'], value):
        raise ValidationError("Username must be 3-32 alphanumeric characters")

    return value


def _validate_channel_id(value: Any) -> int:
    """Validate channel/group ID."""
    try:
        channel_id = int(value)
    except (ValueError, TypeError):
        raise ValidationError("Channel ID must be an integer")

    if not re.match(PATTERNS['channel_id'], str(value)):
        raise ValidationError("Invalid channel ID format")

    return channel_id


def _validate_message_id(value: Any) -> int:
    """Validate message ID."""
    try:
        msg_id = int(value)
    except (ValueError, TypeError):
        raise ValidationError("Message ID must be an integer")

    if not re.match(PATTERNS['message_id'], str(value)):
        raise ValidationError("Invalid message ID format")

    return msg_id


def _validate_url(value: str) -> str:
    """Validate URL."""
    value = _validate_string(value, max_length=2048)

    if not re.match(PATTERNS['url'], value):
        raise ValidationError("Invalid URL format")

    return value


def _validate_date(value: str) -> str:
    """Validate date (YYYY-MM-DD format)."""
    value = _validate_string(value)

    if not re.match(PATTERNS['date'], value):
        raise ValidationError("Date must be in YYYY-MM-DD format")

    # Verify it's a valid date
    try:
        from datetime import datetime
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        raise ValidationError("Invalid date")

    return value


def _validate_bool(value: Any) -> bool:
    """Validate boolean input."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    if isinstance(value, int):
        return value != 0

    raise ValidationError("Value must be boolean")


def _validate_list(value: Any) -> list:
    """Validate list input."""
    if not isinstance(value, list):
        raise ValidationError("Value must be a list")

    if len(value) > 1000:
        raise ValidationError("List too large (max: 1000 items)")

    return value


def _validate_dict(value: Any) -> dict:
    """Validate dictionary input."""
    if not isinstance(value, dict):
        raise ValidationError("Value must be a dictionary")

    if len(value) > 100:
        raise ValidationError("Dictionary too large (max: 100 keys)")

    return value


def sanitize_string(value: str, allow_html: bool = False) -> str:
    """
    Sanitize string by escaping dangerous content.

    Args:
        value: String to sanitize
        allow_html: Whether to allow HTML (still removes dangerous tags)

    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return str(value)

    value = _validate_string(value)

    if allow_html:
        # Remove only dangerous tags/attributes
        return _remove_dangerous_html(value)
    else:
        # Escape all HTML
        return html_escape(value)


def _remove_dangerous_html(value: str) -> str:
    """Remove dangerous HTML tags and attributes."""
    # Remove script tags
    value = re.sub(r'<script[^>]*>.*?</script>', '', value, flags=re.DOTALL | re.IGNORECASE)

    # Remove event handlers
    for attr in DANGEROUS_ATTRS:
        value = re.sub(rf'{attr}\s*=\s*["\'][^"\']*["\']', '', value, flags=re.IGNORECASE)

    # Remove dangerous tags
    for tag in DANGEROUS_TAGS:
        value = re.sub(
            rf'<{tag}[^>]*>.*?</{tag}>',
            '',
            value,
            flags=re.DOTALL | re.IGNORECASE
        )
        value = re.sub(rf'<{tag}[^>]*/>', '', value, flags=re.IGNORECASE)

    return value


def validate_json_payload(data: Dict, schema: Dict) -> Dict:
    """
    Validate JSON payload against a schema.

    Args:
        data: JSON payload to validate
        schema: Schema dict with keys and validation specs

    Returns:
        Validated and sanitized data

    Raises:
        ValidationError: If validation fails
    """
    validated = {}

    for key, spec in schema.items():
        if key not in data:
            if spec.get('required', True):
                raise ValidationError(f"Missing required field: {key}")
            validated[key] = spec.get('default')
            continue

        try:
            validated[key] = validate_input(
                data[key],
                spec['type'],
                required=spec.get('required', True),
                min_length=spec.get('min_length'),
                max_length=spec.get('max_length'),
                pattern=spec.get('pattern')
            )
        except ValidationError as e:
            raise ValidationError(f"Field '{key}': {str(e)}")

    return validated
