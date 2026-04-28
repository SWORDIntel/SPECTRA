"""SPECTRA MSNET bridge."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


KNOWN_MSNET_KINDS = {
    "msnet.ping",
    "spectra.caas.autonomous.toggle.request",
    "spectra.caas.process_queue.request",
    "spectra.caas.flagged_channel.request",
    "spectra.caas.invite_list.request",
    "spectra.caas.tracked_target.request",
    "spectra.caas.discover.request",
    "spectra.caas.discover.response",
    "spectra.caas.autonomous.started",
    "spectra.caas.autonomous.stopped",
    "spectra.caas.process_queue.started",
    "spectra.caas.invite_list.updated",
    "spectra.caas.flagged_channel.updated",
    "spectra.caas.tracked_target.updated",
}


def _normalize_kind(value: str) -> str:
    return str(value or "unknown").strip().lower().replace(" ", "_")


def _classify_kind(kind: str) -> tuple[str, bool]:
    normalized = _normalize_kind(kind)
    if normalized == "msnet.ping":
        return "ping", True
    if normalized in KNOWN_MSNET_KINDS:
        return "route", True
    if normalized.startswith(("spectra.", "argus.", "directeye.", "stalker.")):
        return "route", True
    return "observe", False


def _normalize_targets(raw_targets: str) -> list[str]:
    return [item.strip() for item in raw_targets.split(",") if item.strip()]


@dataclass
class MSNETConfig:
    enabled: bool
    node_id: str = "spectra-node"
    source_id: str = "spectra-node"
    service_id: str = "spectra"
    endpoint_path: str = "/api/v1/msnet/event"
    targets: tuple[str, ...] = ()
    auth_token: str = ""
    timeout_seconds: int = 3
    emit_events: bool = True


class MsnetBridge:
    def __init__(self, config: MSNETConfig):
        self.config = config
        self.enabled = bool(config.enabled)

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "node_id": self.config.node_id,
            "source_id": self.config.source_id,
            "service_id": self.config.service_id,
            "endpoint_path": self.config.endpoint_path,
            "target_count": len(self.config.targets),
        }

    def _normalize_target_url(self, raw_target: str) -> str:
        target = raw_target.strip().rstrip("/")
        if not target:
            return target
        if target.startswith("http://") or target.startswith("https://"):
            return target if target.endswith(self.config.endpoint_path) else f"{target}{self.config.endpoint_path}"
        return f"http://{target}{self.config.endpoint_path}"

    def _build_message(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe_payload = payload if isinstance(payload, dict) else {"value": payload}
        return {
            "msnet_kind": kind,
            "kind": kind,
            "source": self.config.source_id,
            "service": self.config.service_id,
            "service_id": self.config.node_id,
            "ts": time.time(),
            "payload": safe_payload,
        }

    def parse_payload(self, raw: bytes | str | Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if isinstance(raw, (bytes, str)):
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            parsed = json.loads(raw or "{}")
        else:
            parsed = raw

        if not isinstance(parsed, dict):
            raise ValueError("msnet payload must be a JSON object")

        if "msnet_payload" in parsed and isinstance(parsed["msnet_payload"], str):
            decoded = base64.b64decode(parsed["msnet_payload"]).decode("utf-8", errors="ignore")
            wrapped = json.loads(decoded)
            if isinstance(wrapped, dict):
                parsed = wrapped

        kind = str(parsed.get("kind") or parsed.get("msnet_kind") or "unknown")
        payload = parsed.get("payload")
        if not isinstance(payload, dict):
            payload = {"value": payload}

        payload = dict(payload)
        payload.setdefault("msnet_source", str(parsed.get("source") or self.config.node_id))
        return kind, payload

    async def emit(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled or not self.config.emit_events:
            return {"enabled": self.enabled, "sent": 0, "failed": 0, "targets": len(self.config.targets)}

        data = json.dumps(self._build_message(kind, payload)).encode("utf-8")
        sent = 0
        failed = 0

        for target in self.config.targets:
            url = self._normalize_target_url(target)
            if not url:
                failed += 1
                continue
            headers = {"Content-Type": "application/json"}
            if self.config.auth_token:
                headers["x-msnet-token"] = self.config.auth_token
                headers["Authorization"] = f"Bearer {self.config.auth_token}"

            request = Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=float(self.config.timeout_seconds or 3)) as response:
                    status = response.getcode() or 0
                    if 200 <= int(status) < 300:
                        sent += 1
                    else:
                        failed += 1
            except (HTTPError, URLError, ValueError):
                failed += 1

        return {"enabled": self.enabled, "sent": sent, "failed": failed, "targets": len(self.config.targets)}

    def handle_inbound(self, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = _normalize_kind(kind)
        action, supported = _classify_kind(normalized)

        return {
            "received": True,
            "kind": normalized,
            "source": payload.get("msnet_source", self.config.node_id),
            "service": payload.get("service", self.config.service_id),
            "action": action,
            "supported": supported,
            "status": "pong" if action == "ping" else "received",
            "ts": payload.get("msnet_ts", time.time()),
        }


def create_msnet_bridge() -> MsnetBridge:
    from os import environ

    raw_targets = _normalize_targets(environ.get("MSNET_TARGETS", "") or "")
    config = MSNETConfig(
        enabled=environ.get("MSNET_ENABLED", "false").lower() == "true",
        node_id=environ.get("MSNET_NODE_ID", "spectra-node"),
        source_id=environ.get("MSNET_SOURCE_ID", environ.get("MSNET_NODE_ID", "spectra-node")),
        service_id=environ.get("MSNET_SERVICE_ID", "spectra"),
        endpoint_path=environ.get("MSNET_ENDPOINT_PATH", "/api/v1/msnet/event"),
        targets=tuple(raw_targets),
        auth_token=environ.get("MSNET_AUTH_TOKEN", ""),
        timeout_seconds=int(environ.get("MSNET_TIMEOUT_SECONDS", "3") or 3),
        emit_events=environ.get("MSNET_EMIT_EVENTS", "true").lower() != "false",
    )
    return MsnetBridge(config)
