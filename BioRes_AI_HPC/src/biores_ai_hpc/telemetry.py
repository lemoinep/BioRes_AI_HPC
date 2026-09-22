from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any


class FaultDomain(str, Enum):
    INFRASTRUCTURE = "infrastructure"
    DATA = "data"
    DECISION = "decision"


@dataclass(frozen=True)
class TelemetryEvent:
    event_type: str
    source: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    attempt_id: int | None = None
    domain: FaultDomain | None = None
    severity: str = "info"
    timestamp_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        event = asdict(self)

        event["domain"] = (
            self.domain.value if self.domain is not None else None
        )

        event["timestamp_utc"] = (
            self.timestamp_utc
            or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        )

        return event

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )


class JsonlEventLogger:
    def __init__(self, root: str | Path, run_id: str) -> None:
        self.run_directory = Path(root) / run_id
        self.run_directory.mkdir(parents=True, exist_ok=True)
        self.path = self.run_directory / "events.jsonl"

    def write(self, event: TelemetryEvent) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(event.to_json())
            stream.write("\n")