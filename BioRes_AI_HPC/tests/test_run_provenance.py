from biores_ai_hpc.telemetry import build_run_summary


def test_summary_preserves_scenario_provenance() -> None:
    scenario = {
        "schema_version": 1,
        "scenario_id": "cascade_test",
        "description": "Provenance test.",
        "worker": {
            "iterations": 100,
            "checkpoint_interval": 20,
            "first_fail_at": 55,
            "second_fail_at": 85,
            "corrupt_recovery_checkpoint_at": 80,
            "residual_threshold": 0.01,
        },
        "campaign": {
            "run_count": 1,
            "run_id_template": "{campaign_id}-run-{run_number:02d}",
        },
    }

    metadata = {
        "scenario_id": "cascade_test",
        "campaign_id": "campaign-provenance",
        "run_number": 1,
        "scenario_source": "configs/cascade_test.json",
    }

    events = [
        {
            "event_type": "run_started",
            "run_id": "campaign-provenance-run-01",
            "payload": {
                "metadata": metadata,
                "scenario": scenario,
                "scenario_snapshot_file": "scenario_snapshot.json",
            },
        },
        {
            "event_type": "run_completed",
            "run_id": "campaign-provenance-run-01",
            "payload": {
                "final_state": "verified",
                "recovery_count": 2,
            },
        },
    ]

    summary = build_run_summary(events)

    assert summary["metadata"] == metadata
    assert summary["scenario"] == scenario
    assert summary["scenario"]["worker"]["residual_threshold"] == 0.01
    assert summary["scenario_snapshot_file"] == "scenario_snapshot.json"
    assert summary["success"] is True


def test_summary_accepts_events_without_provenance() -> None:
    events = [
        {
            "event_type": "run_started",
            "run_id": "legacy-run",
            "payload": {"iterations": 100},
        },
        {
            "event_type": "run_completed",
            "run_id": "legacy-run",
            "payload": {"final_state": "verified"},
        },
    ]

    summary = build_run_summary(events)

    assert summary["metadata"] == {}
    assert summary["scenario"] is None
    assert summary["scenario_snapshot_file"] is None
    assert summary["success"] is True