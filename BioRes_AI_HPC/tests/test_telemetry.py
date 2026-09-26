
import csv
import json

from biores_ai_hpc.telemetry import (
    analyze_run_summaries_csv,
    build_run_summary,
    export_run_summaries_csv,
    generate_campaign_report,
)

def test_build_run_summary_for_cascade_recovery() -> None:
    events = [
        {
            "event_type": "run_started",
            "run_id": "summary-test",
            "payload": {},
        },
        {
            "event_type": "checkpoint_persisted",
            "run_id": "summary-test",
            "attempt_id": 0,
            "payload": {
                "checkpoint_id": "ckpt_20",
                "checksum_valid": True,
            },
        },
        {
            "event_type": "checkpoint_persisted",
            "run_id": "summary-test",
            "attempt_id": 1,
            "payload": {
                "checkpoint_id": "ckpt_80",
                "checksum_valid": False,
            },
        },
        {
            "event_type": "fault_injected",
            "run_id": "summary-test",
            "attempt_id": 0,
            "payload": {
                "iteration": 55,
            },
        },
        {
            "event_type": "checkpoint_selected",
            "run_id": "summary-test",
            "attempt_id": 1,
            "payload": {
                "checkpoint_attempt_id": 0,
                "checkpoint_id": "ckpt_40",
                "iteration": 40,
            },
        },
        {
            "event_type": "checkpoint_selected",
            "run_id": "summary-test",
            "attempt_id": 2,
            "payload": {
                "checkpoint_attempt_id": 1,
                "checkpoint_id": "ckpt_60",
                "iteration": 60,
            },
        },
        {
            "event_type": "run_completed",
            "run_id": "summary-test",
            "payload": {
                "final_state": "verified",
                "recovery_count": 2,
                "final_checkpoint": "ckpt_100",
                "final_checkpoint_attempt": 2,
                "final_residual": 0.005,
                "total_experiment_time_s": 4.5,
                "total_recovery_runtime_s": 2.8,
                "verification_time_s": 0.003,
            },
        },
    ]

    summary = build_run_summary(events)

    assert summary["schema_version"] == 1
    assert summary["run_id"] == "summary-test"
    assert summary["final_state"] == "verified"
    assert summary["success"] is True
    assert summary["recovery_count"] == 2
    assert summary["fault_count"] == 1
    assert summary["checkpoint_count"] == 2
    assert summary["valid_checkpoint_count"] == 1
    assert summary["invalid_checkpoint_count"] == 1
    assert summary["final_checkpoint"] == {
        "attempt_id": 2,
        "checkpoint_id": "ckpt_100",
    }
    assert summary["recovery_sources"] == [
        {
            "recovery_attempt_id": 1,
            "checkpoint_attempt_id": 0,
            "checkpoint_id": "ckpt_40",
            "iteration": 40,
        },
        {
            "recovery_attempt_id": 2,
            "checkpoint_attempt_id": 1,
            "checkpoint_id": "ckpt_60",
            "iteration": 60,
        },
    ]

def test_export_run_summaries_csv(tmp_path) -> None:
    runs_root = tmp_path / "runs"
    first_run = runs_root / "run-a"
    second_run = runs_root / "run-b"

    first_run.mkdir(parents=True)
    second_run.mkdir(parents=True)

    (first_run / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-a",
                "success": True,
                "final_state": "verified",
                "fault_count": 2,
                "recovery_count": 2,
                "checkpoint_count": 6,
                "valid_checkpoint_count": 5,
                "invalid_checkpoint_count": 1,
                "final_checkpoint": {
                    "attempt_id": 2,
                    "checkpoint_id": "ckpt_100",
                },
                "metrics": {
                    "final_residual": 0.005,
                    "total_experiment_time_s": 4.5,
                    "total_recovery_runtime_s": 2.8,
                    "verification_time_s": 0.003,
                },
                "recovery_sources": [
                    {
                        "recovery_attempt_id": 1,
                        "checkpoint_attempt_id": 0,
                        "checkpoint_id": "ckpt_40",
                        "iteration": 40,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (second_run / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run-b",
                "success": False,
                "final_state": "failed",
                "fault_count": 1,
                "recovery_count": 0,
                "checkpoint_count": 2,
                "valid_checkpoint_count": 2,
                "invalid_checkpoint_count": 0,
                "final_checkpoint": {
                    "attempt_id": None,
                    "checkpoint_id": None,
                },
                "metrics": {
                    "final_residual": None,
                    "total_experiment_time_s": 1.2,
                    "total_recovery_runtime_s": 0.0,
                    "verification_time_s": None,
                },
                "recovery_sources": [],
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "reports" / "runs_summary.csv"

    written_path = export_run_summaries_csv(
        runs_root=runs_root,
        output_path=output_path,
    )

    assert written_path == output_path
    assert output_path.exists()

    with output_path.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 2
    assert rows[0]["run_id"] == "run-a"
    assert rows[0]["success"] == "True"
    assert rows[0]["final_checkpoint_id"] == "ckpt_100"
    assert rows[0]["recovery_source_count"] == "1"
    assert rows[1]["run_id"] == "run-b"
    assert rows[1]["success"] == "False"
    assert rows[1]["final_state"] == "failed"
    assert rows[1]["recovery_source_count"] == "0"

def test_analyze_run_summaries_csv(tmp_path) -> None:
    csv_path = tmp_path / "runs_summary.csv"

    csv_path.write_text(
        "\n".join(
            [
                (
                    "run_id,success,fault_count,recovery_count,"
                    "invalid_checkpoint_count,"
                    "total_experiment_time_s,"
                    "total_recovery_runtime_s,"
                    "verification_time_s"
                ),
                "run-a,True,2,2,1,4.0,2.0,0.004",
                "run-b,True,2,2,1,6.0,3.0,0.006",
                "run-c,False,1,0,0,1.0,0.0,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "campaign_summary.json"

    written_path = analyze_run_summaries_csv(
        csv_path=csv_path,
        output_path=output_path,
    )

    assert written_path == output_path
    assert output_path.exists()

    summary = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary["schema_version"] == 1
    assert summary["total_runs"] == 3
    assert summary["successful_runs"] == 2
    assert summary["failed_runs"] == 1
    assert summary["success_rate_percent"] == 100.0 * 2 / 3
    assert summary["totals"] == {
        "faults": 5,
        "recoveries": 4,
        "invalid_checkpoints": 2,
    }
    assert summary["failed_run_ids"] == ["run-c"]

    assert summary["timing_seconds"]["total_experiment"] == {
        "mean": 11.0 / 3.0,
        "median": 4.0,
        "min": 1.0,
        "max": 6.0,
    }
    assert summary["timing_seconds"]["recovery"] == {
        "mean": 5.0 / 3.0,
        "median": 2.0,
        "min": 0.0,
        "max": 3.0,
    }
    assert summary["timing_seconds"]["verification"] == {
        "mean": 0.005,
        "median": 0.005,
        "min": 0.004,
        "max": 0.006,
    }


def test_generate_campaign_report(tmp_path) -> None:
    csv_path = tmp_path / "runs_summary.csv"
    campaign_path = tmp_path / "campaign_summary.json"
    output_path = tmp_path / "campaign_report.md"

    csv_path.write_text(
        "\n".join(
            [
                (
                    "run_id,success,final_state,fault_count,"
                    "recovery_count,invalid_checkpoint_count,"
                    "final_checkpoint_id,final_residual,"
                    "total_experiment_time_s"
                ),
                (
                    "run-a,True,verified,2,2,1,"
                    "ckpt_100,0.005,4.5"
                ),
                (
                    "run-b,False,failed,1,0,0,"
                    ",,1.2"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    campaign_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "total_runs": 2,
                "successful_runs": 1,
                "failed_runs": 1,
                "success_rate_percent": 50.0,
                "totals": {
                    "faults": 3,
                    "recoveries": 2,
                    "invalid_checkpoints": 1,
                },
                "timing_seconds": {
                    "total_experiment": {
                        "mean": 2.85,
                        "median": 2.85,
                        "min": 1.2,
                        "max": 4.5,
                    },
                    "recovery": {
                        "mean": 1.4,
                        "median": 1.4,
                        "min": 0.0,
                        "max": 2.8,
                    },
                    "verification": {
                        "mean": 0.003,
                        "median": 0.003,
                        "min": 0.003,
                        "max": 0.003,
                    },
                },
                "failed_run_ids": ["run-b"],
            }
        ),
        encoding="utf-8",
    )

    written_path = generate_campaign_report(
        csv_path=csv_path,
        campaign_summary_path=campaign_path,
        output_path=output_path,
    )

    assert written_path == output_path
    assert output_path.exists()

    report = output_path.read_text(encoding="utf-8")

    assert "# BioRes-AI/HPC Campaign Report" in report
    assert "| Total runs | 2 |" in report
    assert "| Success rate | 50.00% |" in report
    assert "| run-a | True | verified |" in report
    assert "| run-b | False | failed |" in report
    assert "- `run-b`" in report
    assert "The controller rejects the corrupted `ckpt_80`" in report