from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any
from collections.abc import Iterable
import csv
from statistics import mean, median


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    return float(value)

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

def build_run_summary(
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    event_list = list(events)

    run_started = next(
        (
            event
            for event in event_list
            if event.get("event_type") == "run_started"
        ),
        None,
    )

    run_completed = next(
        (
            event
            for event in reversed(event_list)
            if event.get("event_type") == "run_completed"
        ),
        None,
    )

    checkpoint_events = [
        event
        for event in event_list
        if event.get("event_type") == "checkpoint_persisted"
    ]

    fault_events = [
        event
        for event in event_list
        if event.get("event_type") == "fault_injected"
    ]

    selection_events = [
        event
        for event in event_list
        if event.get("event_type") == "checkpoint_selected"
    ]

    valid_checkpoint_count = sum(
        bool(event.get("payload", {}).get("checksum_valid", False))
        for event in checkpoint_events
    )

    invalid_checkpoint_count = (
        len(checkpoint_events) - valid_checkpoint_count
    )

    recovery_sources = [
        {
            "recovery_attempt_id": event.get("attempt_id"),
            "checkpoint_attempt_id": event.get("payload", {}).get(
                "checkpoint_attempt_id"
            ),
            "checkpoint_id": event.get("payload", {}).get(
                "checkpoint_id"
            ),
            "iteration": event.get("payload", {}).get("iteration"),
        }
        for event in selection_events
    ]

    completion_payload = (
        run_completed.get("payload", {})
        if run_completed is not None
        else {}
    )

    final_checkpoint_id = completion_payload.get("final_checkpoint")
    final_checkpoint_attempt = completion_payload.get(
        "final_checkpoint_attempt"
    )
    final_state = completion_payload.get("final_state")

    return {
        "schema_version": 1,
        "run_id": (
            run_completed.get("run_id")
            if run_completed is not None
            else (
                run_started.get("run_id")
                if run_started is not None
                else None
            )
        ),
        "final_state": final_state,
        "success": final_state == "verified",
        "recovery_count": completion_payload.get("recovery_count", 0),
        "fault_count": len(fault_events),
        "checkpoint_count": len(checkpoint_events),
        "valid_checkpoint_count": valid_checkpoint_count,
        "invalid_checkpoint_count": invalid_checkpoint_count,
        "recovery_sources": recovery_sources,
        "final_checkpoint": {
            "attempt_id": final_checkpoint_attempt,
            "checkpoint_id": final_checkpoint_id,
        },
        "metrics": {
            "final_residual": completion_payload.get("final_residual"),
            "total_experiment_time_s": completion_payload.get(
                "total_experiment_time_s"
            ),
            "total_recovery_runtime_s": completion_payload.get(
                "total_recovery_runtime_s"
            ),
            "verification_time_s": completion_payload.get(
                "verification_time_s"
            ),
        },
    }


def write_run_summary(event_logger: JsonlEventLogger) -> Path:
    events: list[dict[str, Any]] = []

    with event_logger.path.open("r", encoding="utf-8") as stream:
        for line in stream:
            stripped = line.strip()

            if not stripped:
                continue

            events.append(json.loads(stripped))

    summary = build_run_summary(events)
    summary_path = event_logger.run_directory / "summary.json"

    with summary_path.open("w", encoding="utf-8") as stream:
        json.dump(
            summary,
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")

    return summary_path

def collect_run_summaries(root: str | Path) -> list[dict[str, Any]]:
    runs_root = Path(root)

    if not runs_root.exists():
        return []

    summaries: list[dict[str, Any]] = []

    for summary_path in sorted(runs_root.glob("*/summary.json")):
        with summary_path.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)

        summary["_summary_path"] = str(summary_path)
        summaries.append(summary)

    return summaries


def export_run_summaries_csv(
    runs_root: str | Path,
    output_path: str | Path,
) -> Path:
    summaries = collect_run_summaries(runs_root)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "run_id",
        "schema_version",
        "success",
        "final_state",
        "fault_count",
        "recovery_count",
        "checkpoint_count",
        "valid_checkpoint_count",
        "invalid_checkpoint_count",
        "final_checkpoint_attempt",
        "final_checkpoint_id",
        "final_residual",
        "total_experiment_time_s",
        "total_recovery_runtime_s",
        "verification_time_s",
        "recovery_source_count",
        "recovery_sources",
        "summary_path",
    ]

    with destination.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fieldnames,
        )
        writer.writeheader()

        for summary in summaries:
            final_checkpoint = summary.get("final_checkpoint", {})
            metrics = summary.get("metrics", {})
            recovery_sources = summary.get("recovery_sources", [])

            writer.writerow(
                {
                    "run_id": summary.get("run_id"),
                    "schema_version": summary.get("schema_version"),
                    "success": summary.get("success"),
                    "final_state": summary.get("final_state"),
                    "fault_count": summary.get("fault_count"),
                    "recovery_count": summary.get("recovery_count"),
                    "checkpoint_count": summary.get("checkpoint_count"),
                    "valid_checkpoint_count": summary.get(
                        "valid_checkpoint_count"
                    ),
                    "invalid_checkpoint_count": summary.get(
                        "invalid_checkpoint_count"
                    ),
                    "final_checkpoint_attempt": final_checkpoint.get(
                        "attempt_id"
                    ),
                    "final_checkpoint_id": final_checkpoint.get(
                        "checkpoint_id"
                    ),
                    "final_residual": metrics.get("final_residual"),
                    "total_experiment_time_s": metrics.get(
                        "total_experiment_time_s"
                    ),
                    "total_recovery_runtime_s": metrics.get(
                        "total_recovery_runtime_s"
                    ),
                    "verification_time_s": metrics.get(
                        "verification_time_s"
                    ),
                    "recovery_source_count": len(recovery_sources),
                    "recovery_sources": json.dumps(
                        recovery_sources,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "summary_path": summary.get("_summary_path"),
                }
            )

    return destination


def _numeric_values(
    rows: Iterable[dict[str, str]],
    field_name: str,
) -> list[float]:
    values: list[float] = []

    for row in rows:
        raw_value = row.get(field_name)

        if raw_value in (None, ""):
            continue

        values.append(float(raw_value))

    return values


def _describe(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }

    return {
        "mean": mean(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def analyze_run_summaries_csv(
    csv_path: str | Path,
    output_path: str | Path,
) -> Path:
    source = Path(csv_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with source.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as stream:
        rows = list(csv.DictReader(stream))

    successful_rows = [
        row
        for row in rows
        if str(row.get("success", "")).strip().lower() == "true"
    ]

    failed_run_ids = [
        str(row.get("run_id"))
        for row in rows
        if str(row.get("success", "")).strip().lower() != "true"
    ]

    total_runs = len(rows)
    successful_runs = len(successful_rows)
    failed_runs = total_runs - successful_runs

    summary = {
        "schema_version": 1,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "success_rate_percent": (
            (100.0 * successful_runs / total_runs)
            if total_runs > 0
            else 0.0
        ),
        "totals": {
            "faults": sum(
                int(row.get("fault_count") or 0)
                for row in rows
            ),
            "recoveries": sum(
                int(row.get("recovery_count") or 0)
                for row in rows
            ),
            "invalid_checkpoints": sum(
                int(row.get("invalid_checkpoint_count") or 0)
                for row in rows
            ),
        },
        "timing_seconds": {
            "total_experiment": _describe(
                _numeric_values(rows, "total_experiment_time_s")
            ),
            "recovery": _describe(
                _numeric_values(rows, "total_recovery_runtime_s")
            ),
            "verification": _describe(
                _numeric_values(rows, "verification_time_s")
            ),
        },
        "failed_run_ids": failed_run_ids,
    }

    with destination.open("w", encoding="utf-8") as stream:
        json.dump(
            summary,
            stream,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")

    return destination


def _format_metric(
    value: float | int | None,
    *,
    decimals: int = 6,
) -> str:
    if value is None:
        return "n/a"

    if isinstance(value, int):
        return str(value)

    return f"{value:.{decimals}f}"


def generate_campaign_report(
    csv_path: str | Path,
    campaign_summary_path: str | Path,
    output_path: str | Path,
) -> Path:
    csv_source = Path(csv_path)
    campaign_source = Path(campaign_summary_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with csv_source.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as stream:
        rows = list(csv.DictReader(stream))

    with campaign_source.open("r", encoding="utf-8") as stream:
        campaign = json.load(stream)

    timing = campaign.get("timing_seconds", {})
    total_timing = timing.get("total_experiment", {})
    recovery_timing = timing.get("recovery", {})
    verification_timing = timing.get("verification", {})
    totals = campaign.get("totals", {})
    failed_run_ids = campaign.get("failed_run_ids", [])

    lines = [
        "# BioRes-AI/HPC Campaign Report",
        "",
        "## Campaign outcome",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total runs | {campaign.get('total_runs', 0)} |",
        f"| Successful runs | {campaign.get('successful_runs', 0)} |",
        f"| Failed runs | {campaign.get('failed_runs', 0)} |",
        (
            "| Success rate | "
            f"{_format_metric(campaign.get('success_rate_percent'), decimals=2)}% |"
        ),
        f"| Injected faults | {totals.get('faults', 0)} |",
        f"| Recoveries performed | {totals.get('recoveries', 0)} |",
        (
            "| Invalid checkpoints rejected | "
            f"{totals.get('invalid_checkpoints', 0)} |"
        ),
        "",
        "## Timing statistics",
        "",
        "| Measure | Mean (s) | Median (s) | Min (s) | Max (s) |",
        "|---|---:|---:|---:|---:|",
        (
            "| Total experiment | "
            f"{_format_metric(total_timing.get('mean'))} | "
            f"{_format_metric(total_timing.get('median'))} | "
            f"{_format_metric(total_timing.get('min'))} | "
            f"{_format_metric(total_timing.get('max'))} |"
        ),
        (
            "| Recovery runtime | "
            f"{_format_metric(recovery_timing.get('mean'))} | "
            f"{_format_metric(recovery_timing.get('median'))} | "
            f"{_format_metric(recovery_timing.get('min'))} | "
            f"{_format_metric(recovery_timing.get('max'))} |"
        ),
        (
            "| Final verification | "
            f"{_format_metric(verification_timing.get('mean'))} | "
            f"{_format_metric(verification_timing.get('median'))} | "
            f"{_format_metric(verification_timing.get('min'))} | "
            f"{_format_metric(verification_timing.get('max'))} |"
        ),
        "",
        "## Run results",
        "",
        (
            "| Run ID | Success | Final state | Faults | Recoveries | "
            "Invalid checkpoints | Final checkpoint | Residual | "
            "Total time (s) |"
        ),
        "|---|---|---|---:|---:|---:|---|---:|---:|",
    ]

    for row in rows:
        lines.append(
            "| "
            f"{row.get('run_id', 'n/a')} | "
            f"{row.get('success', 'n/a')} | "
            f"{row.get('final_state', 'n/a')} | "
            f"{row.get('fault_count', 'n/a')} | "
            f"{row.get('recovery_count', 'n/a')} | "
            f"{row.get('invalid_checkpoint_count', 'n/a')} | "
            f"{row.get('final_checkpoint_id', 'n/a')} | "
            f"{_format_metric(_as_float(row.get('final_residual')))} | "
            f"{_format_metric(_as_float(row.get('total_experiment_time_s')))} |"
        )

    lines.extend(
        [
            "",
            "## Recovery protocol",
            "",
            "Each cascade experiment uses a deterministic recovery scenario:",
            "",
            "- A first controlled worker termination is injected at iteration 55.",
            "- The controller restores the latest valid checkpoint, `ckpt_40`.",
            "- During the first recovery, `ckpt_80` is deliberately corrupted.",
            "- A second controlled termination is injected at iteration 85.",
            "- The controller rejects the corrupted `ckpt_80` and restores `ckpt_60`.",
            "- The final recovery completes at `ckpt_100` and performs integrity and numerical verification.",
            "",
            "## Failed runs",
            "",
        ]
    )

    if failed_run_ids:
        lines.extend(
            f"- `{run_id}`"
            for run_id in failed_run_ids
        )
    else:
        lines.append("No failed runs were recorded.")

    lines.append("")

    with destination.open("w", encoding="utf-8") as stream:
        stream.write("\n".join(lines))

    return destination