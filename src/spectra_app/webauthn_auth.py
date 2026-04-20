"""Local operator auth and WebAuthn backend support for SPECTRA."""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

try:
    from fido2.server import Fido2Server
    from fido2.utils import websafe_decode, websafe_encode
    from fido2.webauthn import (
        AttestedCredentialData,
        PublicKeyCredentialDescriptor,
        PublicKeyCredentialRpEntity,
        PublicKeyCredentialUserEntity,
    )

    FIDO2_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dependency
    FIDO2_AVAILABLE = False
    Fido2Server = None  # type: ignore[assignment]
    AttestedCredentialData = None  # type: ignore[assignment]
    PublicKeyCredentialDescriptor = None  # type: ignore[assignment]
    PublicKeyCredentialRpEntity = None  # type: ignore[assignment]
    PublicKeyCredentialUserEntity = None  # type: ignore[assignment]
    websafe_decode = None  # type: ignore[assignment]
    websafe_encode = None  # type: ignore[assignment]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _jsonify(value: Any) -> Any:
    """Convert WebAuthn objects into browser-friendly JSON values."""
    if isinstance(value, bytes):
        return b64url_encode(value)
    if isinstance(value, Mapping):
        return {key: _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(item) for item in value]
    if hasattr(value, "items") and hasattr(value, "keys"):
        return {key: _jsonify(item) for key, item in value.items()}
    if hasattr(value, "value") and not isinstance(value, str):
        return getattr(value, "value")
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {
            key: _jsonify(item)
            for key, item in value.__dict__.items()
            if not key.startswith("_")
        }
    return value


def _credential_descriptor_from_attested(credential: "AttestedCredentialData") -> Dict[str, Any]:
    return {
        "id": b64url_encode(credential.credential_id),
        "type": "public-key",
    }


@dataclass
class OperatorCredential:
    credential_id: str
    label: str
    sign_count: int = 0
    transports: List[str] = field(default_factory=list)
    public_key: Optional[str] = None
    attested_credential_data: Optional[str] = None
    aaguid: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    last_used_at: Optional[str] = None


@dataclass
class OperatorRecord:
    operator_id: str
    username: str
    display_name: str
    role: str
    active: bool = True
    credentials: List[OperatorCredential] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    last_login_at: Optional[str] = None


class JsonOperatorStore:
    """Persists local operators and WebAuthn metadata to a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._operators: Dict[str, OperatorRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        operators: Dict[str, OperatorRecord] = {}
        for item in payload.get("operators", []):
            credentials = [OperatorCredential(**credential) for credential in item.get("credentials", [])]
            item = dict(item)
            item["credentials"] = credentials
            operator = OperatorRecord(**item)
            operators[operator.operator_id] = operator
        self._operators = operators

    def _save(self) -> None:
        payload = {"operators": [asdict(operator) for operator in self._operators.values()]}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def list_operators(self) -> List[OperatorRecord]:
        return sorted(self._operators.values(), key=lambda operator: operator.username.lower())

    def has_admin(self) -> bool:
        return any(operator.role == "admin" for operator in self._operators.values())

    def get_operator(self, operator_id: str) -> Optional[OperatorRecord]:
        return self._operators.get(operator_id)

    def get_operator_by_username(self, username: str) -> Optional[OperatorRecord]:
        username = username.strip().lower()
        for operator in self._operators.values():
            if operator.username.lower() == username:
                return operator
        return None

    def create_operator(self, username: str, display_name: str, role: str) -> OperatorRecord:
        operator = OperatorRecord(
            operator_id=secrets.token_hex(8),
            username=username.strip(),
            display_name=display_name.strip() or username.strip(),
            role=role,
        )
        self._operators[operator.operator_id] = operator
        self._save()
        return operator

    def update_operator(self, operator: OperatorRecord) -> OperatorRecord:
        operator.updated_at = _utc_now()
        self._operators[operator.operator_id] = operator
        self._save()
        return operator

    def set_operator_active(self, operator_id: str, active: bool) -> Optional[OperatorRecord]:
        operator = self.get_operator(operator_id)
        if operator is None:
            return None
        operator.active = bool(active)
        return self.update_operator(operator)

    def find_operator_by_credential_id(self, credential_id: str) -> Optional[OperatorRecord]:
        for operator in self._operators.values():
            for credential in operator.credentials:
                if credential.credential_id == credential_id:
                    return operator
        return None

    def add_credential(
        self,
        operator_id: str,
        credential_id: str,
        label: str,
        transports: Optional[List[str]] = None,
        public_key: Optional[str] = None,
        attested_credential_data: Optional[str] = None,
        aaguid: Optional[str] = None,
    ) -> OperatorCredential:
        operator = self.get_operator(operator_id)
        if operator is None:
            raise KeyError(operator_id)
        if any(existing.credential_id == credential_id for existing in operator.credentials):
            raise ValueError("Credential is already registered")
        credential = OperatorCredential(
            credential_id=credential_id,
            label=label,
            transports=sorted(set(transports or [])),
            public_key=public_key,
            attested_credential_data=attested_credential_data,
            aaguid=aaguid,
        )
        operator.credentials.append(credential)
        self.update_operator(operator)
        return credential

    def touch_login(self, operator_id: str, credential_id: Optional[str] = None, sign_count: Optional[int] = None) -> None:
        operator = self.get_operator(operator_id)
        if operator is None:
            return
        operator.last_login_at = _utc_now()
        if credential_id:
            for credential in operator.credentials:
                if credential.credential_id == credential_id:
                    credential.last_used_at = operator.last_login_at
                    if sign_count is not None:
                        credential.sign_count = max(int(sign_count), credential.sign_count)
                    break
        self.update_operator(operator)

    def operator_credentials(self, operator_id: str) -> List["AttestedCredentialData"]:
        operator = self.get_operator(operator_id)
        if operator is None:
            return []
        credentials: List[AttestedCredentialData] = []
        for credential in operator.credentials:
            if credential.attested_credential_data:
                credentials.append(AttestedCredentialData(b64url_decode(credential.attested_credential_data)))
        return credentials

    def all_credentials(self) -> List["AttestedCredentialData"]:
        credentials: List[AttestedCredentialData] = []
        for operator in self.list_operators():
            credentials.extend(self.operator_credentials(operator.operator_id))
        return credentials


class WebAuthnUnavailableError(RuntimeError):
    """Raised when a WebAuthn backend is not installed."""


class WebAuthnBackend:
    """Backend abstraction that can be swapped without changing launcher routes."""

    available = False
    backend_name = "unavailable"
    unavailable_reason = "Install a Python WebAuthn backend such as `fido2` to enable YubiKey verification."

    def register_begin(self, user: "PublicKeyCredentialUserEntity", exclude_credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def register_complete(self, state: Dict[str, Any], request_data: Dict[str, Any]) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def authenticate_begin(self, credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def authenticate_complete(self, state: Dict[str, Any], credentials: Sequence["AttestedCredentialData"], request_data: Dict[str, Any]) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def begin_registration(
        self,
        operator: OperatorRecord,
        rp_id: Optional[str] = None,
        rp_name: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def finish_registration(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def begin_authentication(
        self,
        operators: Sequence[OperatorRecord] | None = None,
        rp_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def finish_authentication(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
        operators: Sequence[OperatorRecord] | None = None,
    ) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)


class Fido2WebAuthnBackend(WebAuthnBackend):
    """WebAuthn backend backed by `python-fido2`."""

    available = True
    backend_name = "fido2"
    unavailable_reason = ""

    def __init__(self, rp_id: str, rp_name: str, origin: Optional[str] = None):
        if not FIDO2_AVAILABLE:
            raise WebAuthnUnavailableError("fido2 is not installed")
        self.rp_id = rp_id
        self.rp_name = rp_name
        self.origin = origin
        verify_origin = (lambda candidate_origin: candidate_origin == origin) if origin else None
        self.server = Fido2Server(
            PublicKeyCredentialRpEntity(name=rp_name, id=rp_id),
            verify_origin=verify_origin,
        )

    def register_begin(self, user: "PublicKeyCredentialUserEntity", exclude_credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        options, state = self.server.register_begin(user, credentials=list(exclude_credentials or []))
        return _jsonify(options.public_key), state

    def register_complete(self, state: Dict[str, Any], request_data: Dict[str, Any]) -> Dict[str, Any]:
        auth_data = self.server.register_complete(state, request_data)
        credential_data = auth_data.credential_data
        assert credential_data is not None  # noqa: S101
        return {
            "credential_id": b64url_encode(credential_data.credential_id),
            "attested_credential_data": b64url_encode(bytes(credential_data)),
            "aaguid": getattr(credential_data, "aaguid", None).hex() if getattr(credential_data, "aaguid", None) else None,
            "public_key": getattr(credential_data, "public_key", None).hex() if getattr(credential_data, "public_key", None) else None,
        }

    def authenticate_begin(self, credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        options, state = self.server.authenticate_begin(credentials=list(credentials or []))
        return _jsonify(options.public_key), state

    def authenticate_complete(self, state: Dict[str, Any], credentials: Sequence["AttestedCredentialData"], request_data: Dict[str, Any]) -> Dict[str, Any]:
        credential = self.server.authenticate_complete(state, list(credentials), request_data)
        return {
            "credential_id": b64url_encode(credential.credential_id),
        }

    def begin_registration(
        self,
        operator: OperatorRecord,
        rp_id: Optional[str] = None,
        rp_name: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if rp_id and rp_id != self.rp_id:
            self.__init__(rp_id=rp_id, rp_name=rp_name or self.rp_name, origin=origin or self.origin)
        existing_credentials: List[Any] = []
        for credential in operator.credentials:
            if credential.attested_credential_data:
                existing_credentials.append(AttestedCredentialData(b64url_decode(credential.attested_credential_data)))
        user = PublicKeyCredentialUserEntity(
            id=operator.operator_id.encode("utf-8"),
            name=operator.username,
            display_name=operator.display_name,
        )
        return self.register_begin(user, exclude_credentials=existing_credentials)

    def finish_registration(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.register_complete(state, request_data)

    def begin_authentication(
        self,
        operators: Sequence[OperatorRecord] | None = None,
        rp_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if rp_id and rp_id != self.rp_id:
            self.__init__(rp_id=rp_id, rp_name=self.rp_name, origin=origin or self.origin)
        credentials: List[Any] = []
        for operator in operators or []:
            for credential in operator.credentials:
                if credential.attested_credential_data:
                    credentials.append(AttestedCredentialData(b64url_decode(credential.attested_credential_data)))
        return self.authenticate_begin(credentials=credentials)

    def finish_authentication(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
        operators: Sequence[OperatorRecord] | None = None,
    ) -> Dict[str, Any]:
        credentials: List[AttestedCredentialData] = []
        for operator in operators or []:
            for credential in operator.credentials:
                if credential.attested_credential_data:
                    credentials.append(AttestedCredentialData(b64url_decode(credential.attested_credential_data)))
        return self.authenticate_complete(state, credentials, request_data)


class PlaceholderWebAuthnBackend(WebAuthnBackend):
    """Strict fail-closed backend used when `fido2` is unavailable."""

    def register_begin(self, user: "PublicKeyCredentialUserEntity", exclude_credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def register_complete(self, state: Dict[str, Any], request_data: Dict[str, Any]) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def authenticate_begin(self, credentials: Sequence[Any] | None = None) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def authenticate_complete(self, state: Dict[str, Any], credentials: Sequence["AttestedCredentialData"], request_data: Dict[str, Any]) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def begin_registration(
        self,
        operator: OperatorRecord,
        rp_id: Optional[str] = None,
        rp_name: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def finish_registration(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def begin_authentication(
        self,
        operators: Sequence[OperatorRecord] | None = None,
        rp_id: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        raise WebAuthnUnavailableError(self.unavailable_reason)

    def finish_authentication(
        self,
        request_data: Dict[str, Any],
        state: Dict[str, Any],
        operators: Sequence[OperatorRecord] | None = None,
    ) -> Dict[str, Any]:
        raise WebAuthnUnavailableError(self.unavailable_reason)


class WebAuthnAuthService:
    """Local auth service for operators, sessions, and WebAuthn ceremony state."""

    def __init__(
        self,
        store: JsonOperatorStore,
        backend: Optional[WebAuthnBackend] = None,
        bootstrap_secret: Optional[str] = None,
        rp_id: Optional[str] = None,
        rp_name: str = "SPECTRA",
        origin: Optional[str] = None,
    ):
        self.store = store
        self.backend = backend or (
            Fido2WebAuthnBackend(rp_id=rp_id or "localhost", rp_name=rp_name, origin=origin)
            if FIDO2_AVAILABLE
            else PlaceholderWebAuthnBackend()
        )
        self.bootstrap_secret = bootstrap_secret
        self.rp_id = rp_id or "localhost"
        self.rp_name = rp_name
        self.origin = origin

    def bootstrap_required(self) -> bool:
        return not self.store.has_admin()

    def backend_status(self) -> Dict[str, Any]:
        return {
            "available": self.backend.available,
            "backend": self.backend.backend_name,
            "reason": None if self.backend.available else self.backend.unavailable_reason,
        }

    def public_auth_state(self, current_operator: Optional[OperatorRecord] = None) -> Dict[str, Any]:
        return {
            "bootstrap_required": self.bootstrap_required(),
            "bootstrap_configured": bool(self.bootstrap_secret),
            "webauthn": self.backend_status(),
            "rp_id": self.rp_id,
            "rp_name": self.rp_name,
            "origin": self.origin,
            "operator": self.operator_summary(current_operator) if current_operator else None,
            "operators": self.list_operator_summaries() if current_operator else [],
        }

    def list_operator_summaries(self) -> List[Dict[str, Any]]:
        summaries = []
        for operator in self.store.list_operators():
            summaries.append(self.operator_summary(operator))
        return summaries

    def operator_summary(self, operator: Optional[OperatorRecord]) -> Optional[Dict[str, Any]]:
        if operator is None:
            return None
        return {
            "operator_id": operator.operator_id,
            "username": operator.username,
            "display_name": operator.display_name,
            "role": operator.role,
            "active": operator.active,
            "credential_count": len(operator.credentials),
            "created_at": operator.created_at,
            "last_login_at": operator.last_login_at,
        }

    def validate_bootstrap_secret(self, submitted_secret: Optional[str]) -> bool:
        if not self.bootstrap_secret or not submitted_secret:
            return False
        return secrets.compare_digest(str(submitted_secret), str(self.bootstrap_secret))

    def create_operator(self, username: str, display_name: str, role: str) -> OperatorRecord:
        if self.store.get_operator_by_username(username):
            raise ValueError("Operator already exists")
        return self.store.create_operator(username=username, display_name=display_name, role=role)

    def get_operator_by_username(self, username: str) -> Optional[OperatorRecord]:
        return self.store.get_operator_by_username(username)

    def get_operator(self, operator_id: str) -> Optional[OperatorRecord]:
        return self.store.get_operator(operator_id)

    def ensure_admin_bootstrap(self, username: str, display_name: str, submitted_secret: str) -> OperatorRecord:
        if not self.bootstrap_required():
            raise ValueError("Bootstrap is only available before the first admin is enrolled")
        if not self.validate_bootstrap_secret(submitted_secret):
            raise ValueError("Invalid bootstrap secret")
        operator = self.get_operator_by_username(username)
        if operator is None:
            operator = self.create_operator(username=username, display_name=display_name, role="admin")
        elif operator.role != "admin":
            operator.role = "admin"
            self.store.update_operator(operator)
        return operator

    def start_registration(self, operator: OperatorRecord) -> tuple[Dict[str, Any], Dict[str, Any]]:
        if not FIDO2_AVAILABLE:
            raise WebAuthnUnavailableError(self.backend.unavailable_reason)
        existing_credentials = self.store.operator_credentials(operator.operator_id)
        user = PublicKeyCredentialUserEntity(
            id=operator.operator_id.encode("utf-8"),
            name=operator.username,
            display_name=operator.display_name,
        )
        return self.backend.register_begin(user, exclude_credentials=existing_credentials)

    def finish_registration(self, operator_id: str, state: Dict[str, Any], request_data: Dict[str, Any], label: Optional[str] = None) -> Dict[str, Any]:
        operator = self.get_operator(operator_id)
        if operator is None:
            raise ValueError("Operator not found")
        result = self.backend.register_complete(state, request_data)
        credential_id = result["credential_id"]
        self.store.add_credential(
            operator_id=operator_id,
            credential_id=credential_id,
            label=label or operator.display_name,
            attested_credential_data=result["attested_credential_data"],
            public_key=result.get("public_key"),
            aaguid=result.get("aaguid"),
        )
        return {
            "operator": self.operator_summary(operator),
            "credential_id": credential_id,
        }

    def start_authentication(self, operator: OperatorRecord) -> tuple[Dict[str, Any], Dict[str, Any]]:
        credentials = self.store.operator_credentials(operator.operator_id)
        if not credentials:
            raise ValueError("No registered credentials for operator")
        return self.backend.authenticate_begin(credentials=credentials)

    def finish_authentication(self, state: Dict[str, Any], request_data: Dict[str, Any]) -> OperatorRecord:
        credentials = self.store.all_credentials()
        result = self.backend.authenticate_complete(state, credentials, request_data)
        credential_id = result["credential_id"]
        operator = self.store.find_operator_by_credential_id(credential_id)
        if operator is None:
            raise ValueError("Authenticated credential is not associated with an operator")
        self.store.touch_login(operator.operator_id, credential_id=credential_id)
        return operator
