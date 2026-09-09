"""Deterministic natural-language planning for typed SPECTRA operations."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import OperationEnvelope
from .registry import OperationRegistry


class PlanningError(ValueError):
    """Raised when an operator request cannot be planned safely."""


@dataclass(frozen=True)
class OperationPlan:
    """A validated operation request with human-readable planning context."""

    request: OperationEnvelope
    operation: dict[str, Any]
    assumptions: list[str] = field(default_factory=list)

    def as_dict(self, source: str) -> dict[str, Any]:
        return {
            "kind": "operation_plan",
            "source": source,
            "request": self.request.model_dump(mode="json"),
            "operation": self.operation,
            "assumptions": self.assumptions,
        }


_SENSITIVE_TERMS = re.compile(r"\b(api[_ -]?hash|api[_ -]?id|otp|one[- ]time|password|secret|token|2fa|two[- ]factor)\b", re.I)
_ENTITY_PATTERN = re.compile(r"^(?:https?://t\.me/|tg://resolve\?domain=)?(?:@[-\w]+|-?\d{5,}|[-\w]{3,})$")


class OperationPlanner:
    """Plan a constrained set of common requests without executing them."""

    def __init__(self, registry: OperationRegistry) -> None:
        if not isinstance(registry, OperationRegistry):
            raise TypeError("registry must be an OperationRegistry")
        self.registry = registry

    def plan(self, request_text: str) -> OperationPlan:
        if not isinstance(request_text, str) or not request_text.strip():
            raise PlanningError("Provide a request to plan.")
        source = request_text.strip()
        if _SENSITIVE_TERMS.search(source):
            raise PlanningError("Agent planning does not accept credentials, OTPs, passwords, or tokens. Use account login with environment-backed secrets.")
        tokens = self._tokens(source)
        normalized = " ".join(tokens).lower()
        if self._is_version(normalized):
            return self._build("version", {}, ["No execution is performed by agent plan."])
        if self._is_doctor(normalized):
            capabilities = "capabilit" in normalized or "dependency" in normalized
            return self._build("doctor", {"capabilities": capabilities}, ["No execution is performed by agent plan."])
        if self._is_config_get(tokens, normalized):
            path = tokens[2] if len(tokens) >= 3 and tokens[0].lower() == "config" else self._after_phrase(tokens, {"get", "config"})
            return self._build("config.get", {"path": path}, ["The dotted path is read-only."])
        if self._is_task_show(tokens, normalized):
            task_id = tokens[2] if len(tokens) >= 3 and tokens[0].lower() == "task" else self._after_phrase(tokens, {"show", "task"})
            tail = self._integer_after(tokens, {"--tail", "tail"}, default=10)
            return self._build("task.show", {"task_id": task_id, "tail": tail}, ["Task inspection is local and read-only."])
        if self._is_channel_status(tokens, normalized):
            path = tokens[2] if len(tokens) >= 3 and tokens[0].lower() == "channel" else self._after_phrase(tokens, {"check", "channel", "status"})
            tail = self._integer_after(tokens, {"--tail", "tail"}, default=10)
            return self._build("channel.status", {"export_dir": path, "tail": tail}, ["Export inspection is local and does not contact Telegram."])
        if self._is_discovery(tokens, normalized):
            return self._plan_discovery(tokens, normalized)
        if self._is_network(tokens, normalized):
            return self._plan_network(tokens, normalized)
        if self._is_search(tokens, normalized):
            return self._plan_search(tokens, normalized)
        if self._is_archive(tokens, normalized):
            return self._plan_archive(tokens, normalized)
        if self._is_export(tokens, normalized):
            return self._plan_export(tokens, normalized)
        if "download" in normalized and ("channel" in normalized or "media" in normalized):
            return self._plan_channel_download(tokens)
        raise PlanningError("I could not map that request to a registered operation. Use `spectra operations list` or provide an explicit channel, config, task, status, doctor, or version request.")

    @staticmethod
    def _tokens(source: str) -> list[str]:
        try:
            tokens = shlex.split(source)
        except ValueError as exc:
            raise PlanningError(f"Unable to parse request: {exc}") from exc
        if tokens and tokens[0].lower() in {"spectra", "python", "tgarchive"}:
            tokens = tokens[1:]
            if tokens and tokens[0] == "-m":
                tokens = tokens[2:]
        return tokens

    def _build(self, operation_id: str, arguments: dict[str, Any], assumptions: list[str]) -> OperationPlan:
        definition = self.registry.get(operation_id)
        try:
            validated = definition.request_model.model_validate(arguments)
        except ValidationError as exc:
            raise PlanningError(f"Invalid arguments for {operation_id}: {exc}") from exc
        envelope = OperationEnvelope(operation_id=operation_id, arguments=validated.model_dump(mode="json"), dry_run=True)
        return OperationPlan(envelope, definition.metadata(include_schema=False), assumptions)

    @staticmethod
    def _is_version(normalized: str) -> bool:
        return normalized in {"version", "show version", "what version is spectra"} or normalized.endswith(" version")

    @staticmethod
    def _is_doctor(normalized: str) -> bool:
        return normalized in {"doctor", "health", "check health", "check spectra", "diagnose spectra"} or normalized.startswith("run doctor")

    @staticmethod
    def _is_config_get(tokens: list[str], normalized: str) -> bool:
        return len(tokens) >= 3 and tokens[0].lower() == "config" and tokens[1].lower() == "get" or normalized.startswith("get config ")

    @staticmethod
    def _is_task_show(tokens: list[str], normalized: str) -> bool:
        return len(tokens) >= 3 and tokens[0].lower() == "task" and tokens[1].lower() == "show" or normalized.startswith("show task ")

    @staticmethod
    def _is_channel_status(tokens: list[str], normalized: str) -> bool:
        return len(tokens) >= 3 and tokens[0].lower() == "channel" and tokens[1].lower() == "status" or normalized.startswith("check channel status ")

    @staticmethod
    def _is_discovery(tokens: list[str], normalized: str) -> bool:
        return "discover" in normalized or "crawl" in normalized or (tokens[:2] == ["discovery", "run"])

    @staticmethod
    def _is_network(tokens: list[str], normalized: str) -> bool:
        return (len(tokens) >= 2 and tokens[0].lower() == "network" and tokens[1].lower() == "analyze") or normalized.startswith("analyze network")

    @staticmethod
    def _is_search(tokens: list[str], normalized: str) -> bool:
        return (len(tokens) >= 2 and tokens[0].lower() == "search" and tokens[1].lower() in {"fulltext", "full-text"}) or normalized.startswith("search for ") or normalized.startswith("full text search ")

    @staticmethod
    def _is_archive(tokens: list[str], normalized: str) -> bool:
        return (len(tokens) >= 2 and tokens[0].lower() == "archive" and tokens[1].lower() in {"channel", "channels"}) or normalized.startswith("archive channel ")

    @staticmethod
    def _is_export(tokens: list[str], normalized: str) -> bool:
        return (len(tokens) >= 2 and tokens[0].lower() == "export" and tokens[1].lower() == "table") or normalized.startswith("export table ")

    @staticmethod
    def _value_after(tokens: list[str], markers: set[str]) -> str:
        lowered = [token.lower() for token in tokens]
        for index, token in enumerate(lowered):
            if token in markers and index + 1 < len(tokens):
                return tokens[index + 1]
        raise PlanningError("A value is required for this request.")

    @staticmethod
    def _after_phrase(tokens: list[str], markers: set[str]) -> str:
        lowered = [token.lower() for token in tokens]
        marker_indexes = [index for index, token in enumerate(lowered) if token in markers]
        if not marker_indexes:
            raise PlanningError("A value is required for this request.")
        start = max(marker_indexes) + 1
        for token in tokens[start:]:
            if not token.startswith("--"):
                return token
        raise PlanningError("A value is required for this request.")

    @staticmethod
    def _integer_after(tokens: list[str], markers: set[str], *, default: int) -> int:
        lowered = [token.lower() for token in tokens]
        for index, token in enumerate(lowered):
            if token in markers and index + 1 < len(tokens):
                try:
                    return int(tokens[index + 1])
                except ValueError as exc:
                    raise PlanningError(f"Expected an integer after {tokens[index]}.") from exc
        return default

    def _plan_discovery(self, tokens: list[str], normalized: str) -> OperationPlan:
        seed = self._option_value(tokens, [token.lower() for token in tokens], {"--seed", "seed", "from"})
        seeds_file = self._option_value(tokens, [token.lower() for token in tokens], {"--seeds-file", "seeds-file"})
        crawler_dir = self._option_value(tokens, [token.lower() for token in tokens], {"--crawler-dir", "crawler-dir"})
        if seed is None and seeds_file is None:
            for token in tokens[2:]:
                if token.startswith("@") or token.startswith("-100"):
                    seed = token
                    break
        arguments: dict[str, Any] = {
            "seed": seed,
            "seeds_file": seeds_file,
            "crawler_dir": crawler_dir,
            "depth": self._integer_after(tokens, {"--depth", "depth"}, default=2),
            "messages": self._integer_after(tokens, {"--messages", "messages"}, default=1000),
            "export": self._option_value(tokens, [token.lower() for token in tokens], {"--export", "export"}),
            "parallel": "--parallel" in [token.lower() for token in tokens] or "parallel" in normalized,
            "max_workers": self._integer_after(tokens, {"--max-workers", "workers"}, default=None),
        }
        if arguments["max_workers"] is None:
            arguments.pop("max_workers")
        if arguments["seed"] is None and arguments["seeds_file"] is None:
            raise PlanningError("Discovery needs a seed channel or --seeds-file.")
        return self._build("discovery.run", arguments, ["This is a dry-run crawl plan; it has not contacted Telegram."])

    def _plan_network(self, tokens: list[str], normalized: str) -> OperationPlan:
        lowered = [token.lower() for token in tokens]
        arguments = {
            "crawler_dir": self._option_value(tokens, lowered, {"--crawler-dir", "crawler-dir"}),
            "from_db": "--from-db" in lowered or "from database" in normalized or "from db" in normalized,
            "plot": "--plot" in lowered,
            "metric": self._option_value(tokens, lowered, {"--metric", "metric"}) or "combined",
            "export": self._option_value(tokens, lowered, {"--export", "export"}),
            "top": self._integer_after(tokens, {"--top", "top"}, default=50),
        }
        if arguments["crawler_dir"] is None and not arguments["from_db"]:
            raise PlanningError("Network analysis needs --from-db or a crawler directory.")
        return self._build("network.analyze", arguments, ["Network analysis is planned locally; no crawler or database is modified."])

    def _plan_search(self, tokens: list[str], normalized: str) -> OperationPlan:
        lowered = [token.lower() for token in tokens]
        query = self._option_value(tokens, lowered, {"--query", "query"})
        if query is None:
            markers = {"for", "fulltext", "full-text", "search"}
            query = self._after_phrase(tokens, markers)
        arguments: dict[str, Any] = {
            "query": query,
            "limit": self._integer_after(tokens, {"--limit", "limit"}, default=50),
            "offset": self._integer_after(tokens, {"--offset", "offset"}, default=0),
        }
        channel_id = self._option_value(tokens, lowered, {"--channel-id"})
        if channel_id is None:
            for index, token in enumerate(lowered[:-1]):
                if token == "channel" and not lowered[index + 1].startswith("--"):
                    channel_id = tokens[index + 1]
                    break
        if channel_id is not None:
            try:
                arguments["channel_id"] = int(channel_id)
            except ValueError as exc:
                raise PlanningError("Channel ID must be an integer.") from exc
        return self._build("search.fulltext", arguments, ["Full-text search is local and read-only."])

    def _plan_archive(self, tokens: list[str], normalized: str) -> OperationPlan:
        entity = self._after_phrase(tokens, {"channel", "channels"})
        lowered = [token.lower() for token in tokens]
        return self._build("channel.archive", {
            "entity": entity,
            "auto": "--auto" in lowered,
            "no_media": "--no-media" in lowered,
            "no_avatars": "--no-avatars" in lowered,
            "no_topics": "--no-topics" in lowered,
        }, ["This is a dry-run archive plan; it has not contacted Telegram."])

    def _plan_export(self, tokens: list[str], normalized: str) -> OperationPlan:
        lowered = [token.lower() for token in tokens]
        table = self._after_phrase(tokens, {"table"})
        output_file = self._option_value(tokens, lowered, {"--output-file", "to", "--output"})
        if output_file is None:
            raise PlanningError("Table export needs a destination, for example `to exports/messages.jsonl`.")
        export_format = self._option_value(tokens, lowered, {"--format", "format"})
        if export_format is None:
            export_format = Path(output_file).suffix.lstrip(".") or "jsonl"
        return self._build("export.table", {
            "table": table,
            "output_file": output_file,
            "export_format": export_format,
            "limit": self._integer_after(tokens, {"--limit", "limit"}, default=None),
            "offset": self._integer_after(tokens, {"--offset", "offset"}, default=0),
        }, ["Table export is planned with dry_run enabled; no file is written."])

    def _plan_channel_download(self, tokens: list[str]) -> OperationPlan:
        lowered = [token.lower() for token in tokens]
        entity = self._download_entity(tokens, lowered)
        output_dir = self._option_value(tokens, lowered, {"--output-dir", "--output", "to"})
        if output_dir is None:
            raise PlanningError("A channel download needs a destination, for example `to /fast/ULPs` or `--output-dir /fast/ULPs`.")
        arguments: dict[str, Any] = {
            "entity": entity,
            "output_dir": str(Path(output_dir)),
            "auto": "--auto" in lowered,
            "no_proxy": "--no-proxy" in lowered,
            "no_media": "--no-media" in lowered,
            "media_only": "--media-only" in lowered or "media" in lowered,
            "detach": "--detach" in lowered or "background" in lowered,
            "restart": "--restart" in lowered,
        }
        for option, key, cast in (
            ("--account", "account", str),
            ("--max-connections", "max_connections", int),
            ("--max-retries", "max_retries", int),
            ("--retry-delay", "retry_delay", float),
            ("--progress-interval", "progress_interval", float),
            ("--stall-timeout", "stall_timeout", float),
            ("--limit", "limit", int),
            ("--min-id", "min_id", int),
            ("--max-id", "max_id", int),
        ):
            value = self._option_value(tokens, lowered, {option})
            if value is not None:
                try:
                    arguments[key] = cast(value)
                except ValueError as exc:
                    raise PlanningError(f"Expected a valid value after {option}.") from exc
        if "--fail-fast" in lowered:
            arguments["fail_fast"] = True
        if "--no-retry-flood-waits" in lowered:
            arguments["retry_flood_waits"] = False
        return self._build("channel.download", arguments, [
            "The request is a dry-run plan; it has not contacted Telegram.",
            "Existing complete files will be checked and skipped by the downloader when this operation is executed.",
        ])

    @staticmethod
    def _download_entity(tokens: list[str], lowered: list[str]) -> str:
        skip = {"download", "channel", "media", "all", "files", "from", "to", "the", "of", "in", "and", "--media-only"}
        for index, token in enumerate(tokens):
            if lowered[index] in skip or lowered[index].startswith("--"):
                continue
            if index and lowered[index - 1] == "to":
                continue
            if _ENTITY_PATTERN.match(token) and not Path(token).exists():
                return token
        raise PlanningError("A channel entity is required, such as `@channel` or `-1001234567890`.")

    @staticmethod
    def _option_value(tokens: list[str], lowered: list[str], options: set[str]) -> str | None:
        for index, token in enumerate(lowered):
            if token in options and index + 1 < len(tokens):
                return tokens[index + 1]
        return None
