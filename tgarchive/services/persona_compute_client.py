"""
UWP (Unified Wire Protocol) client for communicating with the ASIC-SOC
compute island daemon.

Sends persona training and inference requests to the island daemon, which
routes them to the appropriate backend (CPU for training, NPU/VPU for
inference).

Wire format:
  Header:  magic(5) + version(1) + target_engine(1) + command_opcode(1)
           + payload_length(8, little-endian)  = 16 bytes total
  Payload: payload_length bytes
  Response: same header format + response payload
"""

import json
import logging
import socket
import struct
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# UWP protocol constants (must match island_uwp.h)
UWP_MAGIC = b"QIHSE"
UWP_VERSION = 1
UWP_HEADER_SIZE = 16

# Target engines
UWP_TARGET_ISLAND = 0x08
UWP_TARGET_NPU = 0x0B

# NPU/persona opcodes (must match island_uwp.h)
UWP_OP_NPU_PERSONA_TRAIN = 0x01
UWP_OP_NPU_PERSONA_GENERATE = 0x02
UWP_OP_NPU_PERSONA_SCORE = 0x03
UWP_OP_NPU_PERSONA_LIST = 0x04
UWP_OP_NPU_PERSONA_INFO = 0x05
UWP_OP_NPU_PERSONA_DELETE = 0x06

# Response status codes
UWP_STATUS_OK = 0
UWP_STATUS_ERROR = 1
UWP_STATUS_NO_BACKEND = 2
UWP_STATUS_BAD_REQUEST = 3
UWP_STATUS_INTERNAL = 4

_STATUS_NAMES = {
    UWP_STATUS_OK: "ok",
    UWP_STATUS_ERROR: "error",
    UWP_STATUS_NO_BACKEND: "no_backend",
    UWP_STATUS_BAD_REQUEST: "bad_request",
    UWP_STATUS_INTERNAL: "internal",
}


class UWPError(Exception):
    """UWP protocol error."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.status_name = _STATUS_NAMES.get(status, f"unknown({status})")
        super().__init__(f"UWP {self.status_name}: {message}")


class UWPClient:
    """Client for the ASIC-SOC island UWP daemon."""

    def __init__(
        self,
        socket_path: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: float = 300.0,
    ):
        self.socket_path = socket_path
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def _connect(self) -> socket.socket:
        if self.socket_path:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
        elif self.host and self.port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        else:
            raise ValueError("Either socket_path or host+port must be set")
        return sock

    def _build_header(
        self, target_engine: int, opcode: int, payload_len: int
    ) -> bytes:
        """Build a 16-byte UWP header.

        Layout: magic(5) + version(1) + target_engine(1) + opcode(1)
                + payload_length(8, little-endian)
        """
        return (
            UWP_MAGIC
            + struct.pack("BBB", UWP_VERSION, target_engine, opcode)
            + struct.pack("<Q", payload_len)
        )

    def _send_request(
        self, target_engine: int, opcode: int, payload: bytes
    ) -> Tuple[int, int, bytes]:
        """Send a UWP request and return (status, resp_opcode, resp_payload)."""
        try:
            if self._sock is None:
                self._sock = self._connect()

            header = self._build_header(target_engine, opcode, len(payload))
            self._sock.sendall(header + payload)

            # Read response header
            resp_header = self._recv_exact(UWP_HEADER_SIZE)
            if len(resp_header) < UWP_HEADER_SIZE:
                raise UWPError(UWP_STATUS_INTERNAL, "incomplete response header")

            magic = resp_header[:5]
            if magic != UWP_MAGIC:
                raise UWPError(UWP_STATUS_INTERNAL, f"bad magic: {magic!r}")

            version = resp_header[5]
            resp_opcode = resp_header[7]  # command_opcode at offset 7
            payload_len = struct.unpack("<Q", resp_header[8:16])[0]

            # Read response payload
            resp_payload = self._recv_exact(payload_len) if payload_len else b""

            # The first byte of payload is the status code
            if len(resp_payload) > 0:
                status = resp_payload[0]
                resp_payload = resp_payload[1:]
            else:
                status = UWP_STATUS_OK

            return status, resp_opcode, resp_payload
        except (socket.timeout, ConnectionRefusedError, FileNotFoundError) as e:
            raise UWPError(UWP_STATUS_INTERNAL, f"connection error: {e}")
        finally:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    # ── Persona operations ──────────────────────────────────────────

    def persona_train(
        self,
        corpus_path: str,
        model_name: str,
        model_type: str = "charlm",
        epochs: Optional[int] = None,
    ) -> dict:
        """Send a training request to the island daemon."""
        req = {
            "corpus_path": corpus_path,
            "model_name": model_name,
            "model_type": model_type,
        }
        if epochs is not None:
            req["epochs"] = epochs
        payload = json.dumps(req).encode("utf-8")
        status, _, resp = self._send_request(
            UWP_TARGET_NPU, UWP_OP_NPU_PERSONA_TRAIN, payload
        )
        if status != UWP_STATUS_OK:
            raise UWPError(status, resp.decode("utf-8", errors="replace"))
        return json.loads(resp) if resp else {}

    def persona_generate(
        self,
        model_name: str,
        prompt: str = "",
        max_tokens: int = 200,
        temperature: float = 0.8,
    ) -> dict:
        """Generate text from a trained char-LM on the VPU."""
        req = {
            "model_name": model_name,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload = json.dumps(req).encode("utf-8")
        status, _, resp = self._send_request(
            UWP_TARGET_NPU, UWP_OP_NPU_PERSONA_GENERATE, payload
        )
        if status != UWP_STATUS_OK:
            raise UWPError(status, resp.decode("utf-8", errors="replace"))
        return json.loads(resp) if resp else {}

    def persona_score(self, model_name: str, text: str) -> dict:
        """Score text against a persona classifier on the VPU."""
        req = {"model_name": model_name, "text": text}
        payload = json.dumps(req).encode("utf-8")
        status, _, resp = self._send_request(
            UWP_TARGET_NPU, UWP_OP_NPU_PERSONA_SCORE, payload
        )
        if status != UWP_STATUS_OK:
            raise UWPError(status, resp.decode("utf-8", errors="replace"))
        return json.loads(resp) if resp else {}

    def persona_list_models(self) -> dict:
        """List trained persona models on the island."""
        payload = b""
        status, _, resp = self._send_request(
            UWP_TARGET_NPU, UWP_OP_NPU_PERSONA_LIST, payload
        )
        if status != UWP_STATUS_OK:
            raise UWPError(status, resp.decode("utf-8", errors="replace"))
        return json.loads(resp) if resp else {"models": []}

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
