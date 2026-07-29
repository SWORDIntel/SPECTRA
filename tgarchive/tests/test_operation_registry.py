from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from tgarchive.operations.builtin import create_builtin_registry
from tgarchive.operations.models import OperationEnvelope, OperationResult
from tgarchive.operations.registry import (
    OperationDefinition,
    OperationRegistry,
    OperationUnavailable,
)


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doubled: int


def _registry(handler: Any) -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(
        OperationDefinition(
            operation_id="test.typed",
            title="Typed",
            summary="Exercise typed operation execution.",
            group="test",
            request_model=Request,
            result_model=Result,
            handler=handler,
        )
    )
    return registry


def test_execute_validates_and_normalizes_raw_handler_result() -> None:
    result = _registry(lambda arguments, _context: {"doubled": arguments.value * 2}).execute(
        OperationEnvelope(
            operation_id="test.typed",
            arguments={"value": 4},
            idempotency_key="typed-4",
        )
    )

    assert result.status == "completed"
    assert result.result == {"doubled": 8}
    assert result.idempotency_key == "typed-4"


@pytest.mark.parametrize(
    "handler",
    [
        lambda _arguments, _context: {"doubled": "not-an-integer"},
        lambda _arguments, _context: {"doubled": 2, "undeclared": True},
        lambda _arguments, _context: OperationResult.completed(
            "test.typed",
            {"missing": 2},
        ),
    ],
)
def test_execute_returns_structured_failure_for_invalid_handler_output(handler: Any) -> None:
    result = _registry(handler).execute(
        OperationEnvelope(
            operation_id="test.typed",
            arguments={"value": 1},
            idempotency_key="invalid-result",
        )
    )

    assert result.status == "failed"
    assert result.result is None
    assert result.idempotency_key == "invalid-result"
    assert result.error is not None
    assert result.error.code == 1
    assert result.error.category == "result_validation"
    assert result.error.message == "Operation returned an invalid result"
    assert result.error.details["result_model"] == "Result"
    assert result.error.details["errors"]
    assert "input" not in result.error.details["errors"][0]


def test_execute_rejects_mismatched_operation_result_identity() -> None:
    result = _registry(
        lambda _arguments, _context: OperationResult.completed(
            "different.operation",
            {"doubled": 2},
        )
    ).execute(OperationEnvelope(operation_id="test.typed", arguments={"value": 1}))

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.category == "result_validation"
    assert result.error.details["errors"][0]["type"] == "operation_id_mismatch"


def test_execute_preserves_structured_handler_failure_without_success_payload() -> None:
    failure = OperationResult(
        operation_id="test.typed",
        status="failed",
        idempotency_key="handler-failure",
    )
    result = _registry(lambda _arguments, _context: failure).execute(
        OperationEnvelope(operation_id="test.typed", arguments={"value": 1})
    )

    assert result is failure


def test_builtin_index_operations_have_distinct_typed_result_contracts() -> None:
    registry = create_builtin_registry()
    expected = {
        "index.status": "IndexStatusResult",
        "index.process": "IndexProcessResult",
        "index.drain": "IndexDrainResult",
        "index.rebuild": "IndexRebuildResult",
        "index.verify": "IndexVerifyResult",
        "index.lookup": "IndexMessageLookupResult",
        "index.lookup-record": "IndexRecordLookupResult",
        "index.graph": "IndexGraphLookupResult",
        "index.backfill-export": "IndexBackfillExportResult",
        "index.backfill-database": "IndexBackfillDatabaseResult",
        "index.scan-archive": "IndexArchiveScanResult",
        "index.benchmark": "IndexBenchmarkResult",
        "index.watch": "IndexWatchResult",
    }

    assert {
        operation_id: registry.get(operation_id).result_model.__name__
        for operation_id in expected
    } == expected


@pytest.mark.parametrize(
    ("operation_id", "arguments"),
    [
        ("index.status", {}),
        ("index.process", {}),
        ("index.drain", {}),
        ("index.rebuild", {}),
        ("index.verify", {}),
        ("index.lookup", {"channel_id": -1001, "message_id": 1}),
        (
            "index.lookup-record",
            {
                "projection": "events",
                "namespace": "task_events",
                "external_id": "1",
            },
        ),
        ("index.graph", {"node_type": "message", "external_id": "-1001:1"}),
        ("index.backfill-export", {"export_dir": "/tmp/export"}),
        ("index.backfill-database", {}),
        ("index.scan-archive", {"archive_path": "/tmp/archive.zip"}),
        ("index.benchmark", {}),
        ("index.watch", {}),
    ],
)
def test_each_builtin_index_result_contract_rejects_generic_output(
    operation_id: str,
    arguments: dict[str, Any],
) -> None:
    registry = create_builtin_registry()
    registry.attach_handler(operation_id, lambda _arguments, _context: {})

    result = registry.execute(
        OperationEnvelope(operation_id=operation_id, arguments=arguments)
    )

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.category == "result_validation"
    assert result.error.details["result_model"] == (
        registry.get(operation_id).result_model.__name__
    )


def test_index_watch_is_a_typed_supervisor_around_index_process() -> None:
    registry = create_builtin_registry()
    definition = registry.get("index.watch")
    schema = registry.schema("index.watch")

    assert definition.handler is None
    assert "repeated typed index.process batches" in definition.summary
    assert schema["request_schema"]["properties"]["poll_interval"]["default"] == 0.1
    assert schema["result_schema"]["required"] == [
        "batches",
        "claimed",
        "processed",
        "failed",
        "worker_errors",
        "elapsed_seconds",
    ]
    with pytest.raises(OperationUnavailable):
        registry.execute(
            OperationEnvelope(operation_id="index.watch", arguments={})
        )
