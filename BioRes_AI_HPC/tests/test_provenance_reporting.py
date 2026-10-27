import csv
import json

import pytest

from biores_ai_hpc.telemetry import (
    analyze_run_summaries_csv,
    export_run_summaries_csv,
    generate_campaign_report,
)


@pytest.mark.parametrize(
    ("final_state", "with_provenance"),
    [
        ("verified", True),
        ("failed", True),
        ("unsafe", True),
        ("failed", False),
    ],
)
def test_provenance_and_failure_details_reach_report(
    tmp_path,
    final_state,
    with_provenance,
) -> None:
    runs_root = tmp_path / "runs"
    run_directory = runs_root / "run-a"
    run_directory.mkdir(parents=True)

    success = final_state == "verified"

    summary = {
        "schema_version": 1,
        "run_id": "run-a",
        "success": success,
        "final_state": final_state,
        "fault_count": 2,
        "recovery_count": 2,
        "invalid_checkpoint_count": 1,
        "metrics": {
            "total_experiment_time_s": 4.0,
            "total_recovery_runtime_s": 2.0,
            "verification_time_s": 0.01,
        },
    }

    reason = "Rejected | numerical result\nSee verification details."

    if with_provenance:
        summary["metadata"] = {
            "scenario_id": "cascade_test",
            "campaign_id": "campaign-test",
            "run_number": 1,
        }
        summary["failure_reason"] = None if success else reason
        summary["failure_phase"] = (
            None if success else "final_verification"
        )

    (run_directory / "summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )

    csv_path = tmp_path / "runs.csv"
    campaign_path = tmp_path / "campaign.json"
    report_path = tmp_path / "report.md"

    export_run_summaries_csv(runs_root, csv_path)

    with csv_path.open("r", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    assert len(rows) == 1
    row = rows[0]

    if with_provenance:
        assert row["scenario_id"] == "cascade_test"
        assert row["campaign_id"] == "campaign-test"
        assert row["run_number"] == "1"
        assert row["failure_reason"] == ("" if success else reason)
        assert row["failure_phase"] == (
            "" if success else "final_verification"
        )
    else:
        for field in (
            "scenario_id",
            "campaign_id",
            "run_number",
            "failure_reason",
            "failure_phase",
        ):
            assert row[field] == ""

    analyze_run_summaries_csv(csv_path, campaign_path)
    generate_campaign_report(csv_path, campaign_path, report_path)

    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")

    assert campaign["successful_runs"] == int(success)
    assert campaign["failed_runs"] == int(not success)
    assert "## Run provenance" in report

    if with_provenance:
        assert "| run-a | cascade_test | campaign-test | 1 |" in report
    else:
        assert "| run-a | n/a | n/a | n/a |" in report

    if success:
        assert "No failed runs were recorded." in report
        assert "- `run-a`" not in report
    else:
        assert "- `run-a`" in report
        assert f"Final state: {final_state}" in report
        assert "No failed runs were recorded." not in report

        if with_provenance:
            assert "Failure phase: final_verification" in report
            assert (
                "Failure reason: Rejected &#124; numerical result"
                "<br>See verification details."
            ) in report
        else:
            assert "Failure phase: n/a" in report
            assert "Failure reason: n/a" in report