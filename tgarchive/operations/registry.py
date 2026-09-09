"""Dependency-light operation registry."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from .models import OperationEnvelope, OperationError, OperationResult


OperationHandler = Callable[[BaseModel, Any], Any]


class OperationUnavailable(RuntimeError):
    """Raised when an operation exists but has no executor in this process."""


@dataclass
class OperationDefinition:
    """Static metadata and schemas for one SPECTRA operation."""

    operation_id: str
    title: str
    summary: str
    group: str
    request_model: type[BaseModel]
    result_model: type[BaseModel]
    local_only: bool = True
    telegram_backed: bool = False
    destructive: bool = False
    supports_dry_run: bool = False
    capability: str | None = None
    cli: str | None = None
    examples: list[dict[str, Any]] = field(default_factory=list)
    handler: OperationHandler | None = None

    def metadata(self, *, include_schema: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation_id": self.operation_id,
            "title": self.title,
            "summary": self.summary,
            "group": self.group,
            "local_only": self.local_only,
            "telegram_backed": self.telegram_backed,
            "destructive": self.destructive,
            "supports_dry_run": self.supports_dry_run,
            "capability": self.capability,
            "cli": self.cli,
            "examples": self.examples,
            "request_model": self.request_model.__name__,
            "result_model": self.result_model.__name__,
            "executable": self.handler is not None,
        }
        if include_schema:
            payload["request_schema"] = self.request_model.model_json_schema()
            payload["result_schema"] = self.result_model.model_json_schema()
        return payload


class OperationRegistry:
    """In-memory operation registry with typed validation."""

    def __init__(self) -> None:
        self._operations: dict[str, OperationDefinition] = {}

    def register(self, definition: OperationDefinition) -> OperationDefinition:
        if definition.operation_id in self._operations:
            raise ValueError(f"Operation already registered: {definition.operation_id}")
        self._operations[definition.operation_id] = definition
        return definition

    def attach_handler(self, operation_id: str, handler: OperationHandler) -> None:
        definition = self.get(operation_id)
        definition.handler = handler

    def get(self, operation_id: str) -> OperationDefinition:
        try:
            return self._operations[operation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown operation: {operation_id}") from exc

    def list(self, *, group: str | None = None, executable: bool | None = None) -> list[OperationDefinition]:
        operations: Iterable[OperationDefinition] = self._operations.values()
        if group:
            operations = [operation for operation in operations if operation.group == group]
        if executable is not None:
            operations = [operation for operation in operations if (operation.handler is not None) is executable]
        return sorted(operations, key=lambda operation: operation.operation_id)

    def schema(self, operation_id: str) -> dict[str, Any]:
        return self.get(operation_id).metadata(include_schema=True)

    def execute(self, envelope: OperationEnvelope | dict[str, Any], context: Any = None) -> OperationResult:
        request = OperationEnvelope.model_validate(envelope)
        definition = self.get(request.operation_id)
        if definition.handler is None:
            raise OperationUnavailable(f"Operation has no local executor: {request.operation_id}")
        try:
            arguments = definition.request_model.model_validate(request.arguments)
        except ValidationError as exc:
            return OperationResult(
                operation_id=request.operation_id,
                status="failed",
                error=OperationError(code=2, category="validation", message="Invalid operation arguments", details={"errors": exc.errors()}),
                idempotency_key=request.idempotency_key,
            )
        result = definition.handler(arguments, context)
        if isinstance(result, OperationResult):
            if result.operation_id != request.operation_id:
                return self._invalid_result(
                    request,
                    definition,
                    [{
                        "type": "operation_id_mismatch",
                        "loc": ["operation_id"],
                        "msg": "Handler result operation_id does not match the request",
                    }],
                )
            if result.result is None and result.status not in {"completed", "dry_run"}:
                return result
            validated = self._validate_result(request, definition, result.result)
            if isinstance(validated, OperationResult):
                return validated
            return result.model_copy(update={"result": validated})
        validated = self._validate_result(request, definition, result)
        if isinstance(validated, OperationResult):
            return validated
        return OperationResult.completed(
            request.operation_id,
            validated,
            dry_run=request.dry_run,
            idempotency_key=request.idempotency_key,
        )

    def _validate_result(
        self,
        request: OperationEnvelope,
        definition: OperationDefinition,
        result: Any,
    ) -> dict[str, Any] | OperationResult:
        try:
            validated = definition.result_model.model_validate(result, strict=True)
        except ValidationError as exc:
            errors = [
                {
                    "type": error["type"],
                    "loc": list(error["loc"]),
                    "msg": error["msg"],
                }
                for error in exc.errors(include_url=False, include_context=False, include_input=False)
            ]
            return self._invalid_result(request, definition, errors)
        return validated.model_dump(mode="python", exclude_unset=True)

    @staticmethod
    def _invalid_result(
        request: OperationEnvelope,
        definition: OperationDefinition,
        errors: list[dict[str, Any]],
    ) -> OperationResult:
        return OperationResult(
            operation_id=request.operation_id,
            status="failed",
            error=OperationError(
                code=1,
                category="result_validation",
                message="Operation returned an invalid result",
                details={
                    "result_model": definition.result_model.__name__,
                    "errors": errors,
                },
            ),
            idempotency_key=request.idempotency_key,
        )
