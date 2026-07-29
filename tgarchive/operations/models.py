"""Shared operation request and result models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


OperationStatus = Literal["pending", "running", "completed", "failed", "cancelled", "dry_run"]


class OperationError(BaseModel):
    """Structured operation error."""

    code: int
    category: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class OperationEvent(BaseModel):
    """Progress or lifecycle event emitted by an operation."""

    event: str
    message: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)


class OperationEnvelope(BaseModel):
    """Common operation request envelope."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    idempotency_key: str | None = None


class OperationResult(BaseModel):
    """Common operation result envelope."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    operation_id: str
    status: OperationStatus
    result: Any = None
    warnings: list[str] = Field(default_factory=list)
    events: list[OperationEvent] = Field(default_factory=list)
    error: OperationError | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    idempotency_key: str | None = None

    @classmethod
    def completed(
        cls,
        operation_id: str,
        result: Any,
        *,
        dry_run: bool = False,
        warnings: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> "OperationResult":
        now = datetime.now(timezone.utc)
        return cls(
            operation_id=operation_id,
            status="dry_run" if dry_run else "completed",
            result=result,
            warnings=warnings or [],
            started_at=now,
            finished_at=now,
            idempotency_key=idempotency_key,
        )
