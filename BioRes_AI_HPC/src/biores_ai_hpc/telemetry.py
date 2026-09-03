from __future__ import annotations

from dataclasses import asdict, dataclass
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
    payload: dict[str, Any]
    domain: FaultDomain | None = None
    severity: str = "info"
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        event = asdict(self)
        event["domain"] = self.domain.value if self.domain else None
        event["timestamp"] = self.timestamp or datetime.now(
            timezone.utc
        ).isoformat()
        return event

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class JsonlEventLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: TelemetryEvent) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(event.to_json())
            stream.write("\n")