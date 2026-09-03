from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable


EventHandler = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class WorkerRunResult:
    return_code: int
    events: tuple[dict[str, Any], ...]
    stderr: str


def run_worker(
    worker: Path,
    *,
    iterations: int,
    checkpoint_interval: int,
    fail_at: int | None = None,
    corrupt_checkpoint_at: int | None = None,
    resume_from: Path | None = None,
    checkpoint_directory: Path | None = None,
    on_event: EventHandler | None = None,
) -> WorkerRunResult:
    """Run the C++ worker and collect its JSON Lines telemetry."""
    command = [
        str(worker),
        "--iterations",
        str(iterations),
        "--checkpoint-interval",
        str(checkpoint_interval),
    ]

    if fail_at is not None:
        command.extend(["--fail-at", str(fail_at)])

    if corrupt_checkpoint_at is not None:
        command.extend(
            ["--corrupt-checkpoint-at", str(corrupt_checkpoint_at)]
        )

    if resume_from is not None:
        command.extend(["--resume-from", str(resume_from)])

    if checkpoint_directory is not None:
        command.extend(
            ["--checkpoint-directory", str(checkpoint_directory)]
        )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    assert process.stdout is not None
    events: list[dict[str, Any]] = []

    for raw_line in process.stdout:
        line = raw_line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            events.append(
                {
                    "event_type": "invalid_worker_output",
                    "source": "biores_bridge",
                    "message": str(error),
                    "raw_line": line,
                }
            )
            continue

        events.append(event)

        if on_event is not None:
            on_event(event)

    stderr = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()

    if stderr.strip():
        events.append(
            {
                "event_type": "worker_stderr",
                "source": "biores_bridge",
                "message": stderr.strip(),
            }
        )

    return WorkerRunResult(
        return_code=return_code,
        events=tuple(events),
        stderr=stderr.strip(),
    )