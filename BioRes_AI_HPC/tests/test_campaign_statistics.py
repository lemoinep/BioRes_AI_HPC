import csv
import json

import pytest

from biores_ai_hpc.telemetry import (
    _describe,
    analyze_run_summaries_csv,
    generate_campaign_report,
)


def test_describe_empty_values() -> None:
    assert _describe([]) == {
        "count": 0,
        "mean": None,
        "median": None,
        "min": None,
        "max": None,
        "sample_stddev": None,
    }


def test_describe_single_value() -> None:
    assert _describe([2.5]) == {
        "count": 1,
        "mean": 2.5,
        "median": 2.5,
        "min": 2.5,
        "max": 2.5,
        "sample_stddev": None,
    }


def test_describe_multiple_values() -> None:
    result = _describe([1.0, 2.0, 3.0])

    assert result["count"] == 3
    assert result["mean"] == pytest.approx(2.0)
    assert result["median"] == pytest.approx(2.0)
    assert result["min"] == pytest.approx(1.0)
    assert result["max"] == pytest.approx(3.0)
    assert result["sample_stddev"] == pytest.approx(1.0)


def test_campaign_statistics_include_failed_runs_and_skip_missing(
    tmp_path,
) -> None:
    csv_path = tmp_path / "runs.csv"
    summary_path = tmp_path / "summary.json"
    report_path = tmp_path / "report.md"

    fields = [
        "run_id",
        "success",
        "final_state",
        "fault_count",
        "recovery_count",
        "invalid_checkpoint_count",
        "total_experiment_time_s",
        "total_recovery_runtime_s",
        "verification_time_s",
    ]

    rows = [
        {
            "run_id": "run-ok",
            "success": "True",
            "final_state": "verified",
            "fault_count": 2,
            "recovery_count": 2,
            "invalid_checkpoint_count": 1,
            "total_experiment_time_s": 4,
            "total_recovery_runtime_s": 2,
            "verification_time_s": 0.01,
        },
        {
            "run_id": "run-failed",
            "success": "False",
            "final_state": "failed",
            "fault_count": 1,
            "recovery_count": 1,
            "invalid_checkpoint_count": 0,
            "total_experiment_time_s": 6,
            "total_recovery_runtime_s": "",
            "verification_time_s": "",
        },
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    analyze_run_summaries_csv(csv_path, summary_path)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["total_runs"] == 2
    assert summary["successful_runs"] == 1
    assert summary["failed_runs"] == 1
    assert summary["success_rate_percent"] == pytest.approx(50.0)
    assert summary["failed_run_ids"] == ["run-failed"]
    assert summary["totals"] == {
        "faults": 3,
        "recoveries": 3,
        "invalid_checkpoints": 1,
    }

    timing = summary["timing_seconds"]

    assert timing["total_experiment"]["count"] == 2
    assert timing["total_experiment"]["mean"] == pytest.approx(5.0)
    assert timing["total_experiment"]["sample_stddev"] == pytest.approx(
        2 ** 0.5
    )

    assert timing["recovery"]["count"] == 1
    assert timing["recovery"]["mean"] == pytest.approx(2.0)
    assert timing["recovery"]["sample_stddev"] is None

    assert timing["verification"]["count"] == 1
    assert timing["verification"]["mean"] == pytest.approx(0.01)

    generate_campaign_report(csv_path, summary_path, report_path)

    report = report_path.read_text(encoding="utf-8")

    assert "Sample std. dev. (s)" in report
    assert "Cumulative recovery runtime per run" in report
    assert "including failed runs" in report
    assert "| Total experiment | 2 | 5.000000 |" in report
    assert "| Cumulative recovery runtime per run | 1 | 2.000000 |" in report
    assert "n/a" in report
    assert "- `run-failed`" in report
    assert "No failed runs were recorded." not in report
    assert "iteration 55" not in report
    assert "`ckpt_40`" not in report