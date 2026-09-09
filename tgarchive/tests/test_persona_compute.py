"""Tests for the UWP persona compute client."""

import json
import os
import socket
import struct
import tempfile
import threading
import time
import pytest

from tgarchive.services.persona_compute_client import (
    UWPClient,
    UWPError,
    UWP_MAGIC,
    UWP_VERSION,
    UWP_HEADER_SIZE,
    UWP_TARGET_NPU,
    UWP_OP_NPU_PERSONA_LIST,
    UWP_OP_NPU_PERSONA_GENERATE,
    UWP_OP_NPU_PERSONA_SCORE,
    UWP_OP_NPU_PERSONA_TRAIN,
    UWP_STATUS_OK,
    UWP_STATUS_NO_BACKEND,
)


def _build_response(opcode: int, status: int, payload: bytes) -> bytes:
    """Build a UWP response packet.

    Layout: magic(5) + version(1) + target(1) + opcode(1)
            + payload_length(8) + payload
    The response payload starts with a status byte.
    """
    resp_payload = struct.pack("B", status) + payload
    header = (
        UWP_MAGIC
        + struct.pack("BBB", UWP_VERSION, UWP_TARGET_NPU, opcode)
        + struct.pack("<Q", len(resp_payload))
    )
    return header + resp_payload


class _MockIslandServer:
    """Mock UWP island daemon for testing."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._server = None
        self._thread = None
        self._running = False
        self.received_requests = []
        self.response_handler = self._default_handler

    @staticmethod
    def _default_handler(target: int, opcode: int, payload: bytes) -> bytes:
        if opcode == UWP_OP_NPU_PERSONA_LIST:
            return _build_response(
                opcode, UWP_STATUS_OK,
                json.dumps({"models": [{"name": "test_model", "type": "charlm"}]}).encode(),
            )
        elif opcode == UWP_OP_NPU_PERSONA_GENERATE:
            return _build_response(
                opcode, UWP_STATUS_OK,
                json.dumps({"text": "hello world", "tokens_generated": 11}).encode(),
            )
        elif opcode == UWP_OP_NPU_PERSONA_SCORE:
            return _build_response(
                opcode, UWP_STATUS_OK,
                json.dumps({"score": 0.87}).encode(),
            )
        elif opcode == UWP_OP_NPU_PERSONA_TRAIN:
            return _build_response(
                opcode, UWP_STATUS_OK,
                json.dumps({"onnx_path": "data/persona_models/test.onnx",
                            "final_loss": 0.5, "status": "trained"}).encode(),
            )
        return _build_response(opcode, UWP_STATUS_NO_BACKEND, b"unknown opcode")

    def _serve(self):
        self._server.listen(5)
        while self._running:
            try:
                conn, _ = self._server.accept()
                self._handle_conn(conn)
            except OSError:
                break

    def _handle_conn(self, conn: socket.socket):
        try:
            # Handle one request per connection (client closes after each request)
            header = self._recv_exact(conn, UWP_HEADER_SIZE)
            if len(header) < UWP_HEADER_SIZE:
                return
            magic = header[:5]
            if magic != UWP_MAGIC:
                return
            opcode = header[7]  # command_opcode is at offset 7
            payload_len = struct.unpack("<Q", header[8:16])[0]
            payload = self._recv_exact(conn, payload_len) if payload_len else b""

            self.received_requests.append((opcode, payload))
            resp = self.response_handler(UWP_TARGET_NPU, opcode, payload)
            conn.sendall(resp)
        except Exception:
            pass
        finally:
            conn.close()

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def start(self):
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        self._server.bind(self.socket_path)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        time.sleep(0.1)

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


@pytest.fixture
def mock_island(tmp_path):
    sock_path = str(tmp_path / "island.sock")
    server = _MockIslandServer(sock_path)
    server.start()
    yield server
    server.stop()


def test_persona_list_models(mock_island):
    """Test listing models from the island."""
    client = UWPClient(socket_path=mock_island.socket_path)
    result = client.persona_list_models()
    assert "models" in result
    assert len(result["models"]) == 1
    assert result["models"][0]["name"] == "test_model"


def test_persona_generate(mock_island):
    """Test text generation from the island."""
    client = UWPClient(socket_path=mock_island.socket_path)
    result = client.persona_generate(
        model_name="test_model",
        prompt="hello",
        max_tokens=50,
        temperature=0.8,
    )
    assert result["text"] == "hello world"
    assert result["tokens_generated"] == 11

    # Verify the request was sent correctly
    assert len(mock_island.received_requests) == 1
    opcode, payload = mock_island.received_requests[0]
    assert opcode == UWP_OP_NPU_PERSONA_GENERATE
    req = json.loads(payload)
    assert req["model_name"] == "test_model"
    assert req["prompt"] == "hello"
    assert req["max_tokens"] == 50
    assert req["temperature"] == 0.8


def test_persona_score(mock_island):
    """Test text scoring from the island."""
    client = UWPClient(socket_path=mock_island.socket_path)
    result = client.persona_score(
        model_name="test_clf",
        text="some suspicious text",
    )
    assert result["score"] == 0.87

    opcode, payload = mock_island.received_requests[0]
    assert opcode == UWP_OP_NPU_PERSONA_SCORE
    req = json.loads(payload)
    assert req["model_name"] == "test_clf"
    assert req["text"] == "some suspicious text"


def test_persona_train(mock_island):
    """Test training request to the island."""
    client = UWPClient(socket_path=mock_island.socket_path)
    result = client.persona_train(
        corpus_path="/tmp/corpus.jsonl",
        model_name="my_persona",
        model_type="charlm",
        epochs=10,
    )
    assert result["status"] == "trained"
    assert "onnx_path" in result

    opcode, payload = mock_island.received_requests[0]
    assert opcode == UWP_OP_NPU_PERSONA_TRAIN
    req = json.loads(payload)
    assert req["corpus_path"] == "/tmp/corpus.jsonl"
    assert req["model_name"] == "my_persona"
    assert req["model_type"] == "charlm"
    assert req["epochs"] == 10


def test_uwp_error_handling(mock_island):
    """Test error handling when the island returns an error."""
    def error_handler(target, opcode, payload):
        return _build_response(opcode, UWP_STATUS_NO_BACKEND, b"no VPU available")

    mock_island.response_handler = error_handler
    client = UWPClient(socket_path=mock_island.socket_path)
    with pytest.raises(UWPError) as exc_info:
        client.persona_list_models()
    assert exc_info.value.status == UWP_STATUS_NO_BACKEND


def test_uwp_connection_refused(tmp_path):
    """Test connection error when the daemon is not running."""
    client = UWPClient(socket_path=str(tmp_path / "nonexistent.sock"))
    with pytest.raises(UWPError) as exc_info:
        client.persona_list_models()
    assert "connection error" in str(exc_info.value).lower()
