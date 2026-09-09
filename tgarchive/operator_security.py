"""Password policy and storage helpers for local SPECTRA operators."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "sha384"
PASSWORD_PREFIX = "pbkdf2-sha384"
MIN_PASSWORD_LENGTH = 12


def validate_operator_password_strength(password: str) -> list[str]:
    """Return unmet password policy requirements."""
    if not isinstance(password, str):
        return ["a text password"]
    requirements = [
        (len(password) >= MIN_PASSWORD_LENGTH, f"at least {MIN_PASSWORD_LENGTH} characters"),
        (any(char.islower() for char in password), "a lowercase letter"),
        (any(char.isupper() for char in password), "an uppercase letter"),
        (any(char.isdigit() for char in password), "a number"),
        (any(not char.isalnum() for char in password), "a symbol"),
    ]
    return [description for passed, description in requirements if not passed]


def hash_password(password: str) -> str:
    """Hash a policy-compliant password for storage."""
    problems = validate_operator_password_strength(password)
    if problems:
        raise ValueError("Password must include " + ", ".join(problems))
    salt = secrets.token_bytes(hashlib.sha384().digest_size)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_PREFIX}${PBKDF2_ITERATIONS}${encoded_salt}${encoded_digest}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password against a stored SPECTRA operator hash."""
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    try:
        prefix, iterations_text, encoded_salt, encoded_digest = encoded.split("$", 3)
        iterations = int(iterations_text)
        if prefix != PASSWORD_PREFIX or iterations < PBKDF2_ITERATIONS:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        expected = base64.urlsafe_b64decode(encoded_digest + "=" * (-len(encoded_digest) % 4))
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


__all__ = [
    "hash_password",
    "validate_operator_password_strength",
    "verify_password",
]
