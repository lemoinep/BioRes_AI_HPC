import json
from types import SimpleNamespace

import pytest
import typer

import biores_ai_hpc.cli as cli


@pytest.mark.parametrize(
    ("return_code", "expected_exit", "expected_phase", "reason_fragment"),
    [
        (0, 1, "initial", "Observed: 0"),
        (7, 7, "initial", "Observed: 7"),
        (
            42,
            2,
            "First recovery",
            "No persistent verified checkpoint",
        ),
    ],
)
def test_controlled_failure_writes_summary(
    tmp_path,
    monkeypatch,
    return_code,
    expected_exit,
    expected_phase,
    reason_fragment,
) -> None:
    monkeypatch.chdir(tmp_path)

    worker = tmp_path / "fake_worker.exe"
    worker.touch()

    monkeypatch.setattr(
        cli,
        "run_worker",
        lambda *args, **kwargs: SimpleNamespace(
            return_code=return_code
        ),
    )

    run_id = "failure-test-run"

    with pytest.raises(typer.Exit) as error:
        cli.run_cascade(
            worker=worker,
            iterations=100,
            checkpoint_interval=20,
            first_fail_at=55,
            second_fail_at=85,
            corrupt_recovery_checkpoint_at=80,
            run_id=run_id,
            run_metadata={
                "campaign_id": "failure-test",
                "run_number": 1,
            },
        )

    assert error.value.exit_code == expected_exit

    run_directory = tmp_path / "results" / "runs" / run_id
    summary_path = run_directory / "summary.json"

    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["run_id"] == run_id
    assert summary["success"] is False
    assert summary["final_state"] == "failed"
    assert summary["failure_phase"] == expected_phase
    assert reason_fragment in summary["failure_reason"]

    assert summary["metadata"]["campaign_id"] == "failure-test"
    assert summary["metrics"]["final_residual"] is None
    assert summary["metrics"]["verification_time_s"] is None
    assert summary["metrics"]["total_experiment_time_s"] >= 0

    events = [
        json.loads(line)
        for line in (run_directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    completed = [
        event
        for event in events
        if event["event_type"] == "run_completed"
    ]

    assert len(completed) == 1
    assert completed[0]["payload"]["final_state"] == "failed"


@pytest.mark.parametrize(
    ("final_residual", "expected_success"),
    [
        (0.005, True),
        (0.02, False),
    ],
)
def test_cascade_reaches_final_verification(
    tmp_path,
    monkeypatch,
    final_residual,
    expected_success,
) -> None:
    monkeypatch.chdir(tmp_path)

    worker = tmp_path / "fake_worker.exe"
    worker.touch()

    class FakeCheckpointStore:
        def __init__(self, root, run_id):
            self.root = root / run_id
            self.checkpoints = []

        def attempt_directory(self, attempt_id):
            directory = self.root / f"attempt-{attempt_id}"
            directory.mkdir(parents=True, exist_ok=True)
            return directory

        def write(self, **values):
            metadata = SimpleNamespace(**values)
            self.checkpoints.append(metadata)
            return metadata

        def latest_valid(self):
            for metadata in reversed(self.checkpoints):
                if metadata.checksum_valid:
                    return SimpleNamespace(metadata=metadata)

            return None

    calls = []

    def fake_run_worker(worker_path, **kwargs):
        attempt_id = len(calls)
        calls.append(kwargs)

        observer = kwargs["on_event"]
        directory = kwargs["checkpoint_directory"]

        def emit_checkpoint(iteration, *, valid=True):
            state_path = directory / f"state-{iteration}.json"
            state_path.write_text("{}", encoding="utf-8")

            observer(
                {
                    "event_type": "checkpoint",
                    "checkpoint_id": f"ckpt_{iteration}",
                    "iteration": iteration,
                    "residual": final_residual,
                    "checksum_valid": valid,
                    "state_path": str(state_path),
                }
            )

        if attempt_id == 0:
            emit_checkpoint(20)
            emit_checkpoint(40)

            observer(
                {
                    "event_type": "fault_injected",
                    "iteration": 55,
                    "fault_type": "worker_termination",
                }
            )

            return SimpleNamespace(return_code=42)

        if attempt_id == 1:
            observer(
                {
                    "event_type": "started",
                    "resumed": True,
                    "start_iteration": 40,
                }
            )

            emit_checkpoint(60)
            emit_checkpoint(80, valid=False)

            observer(
                {
                    "event_type": "fault_injected",
                    "iteration": 85,
                    "fault_type": "worker_termination",
                }
            )

            return SimpleNamespace(return_code=42)

        if attempt_id == 2:
            observer(
                {
                    "event_type": "started",
                    "resumed": True,
                    "start_iteration": 60,
                }
            )

            emit_checkpoint(80)
            emit_checkpoint(100)

            observer(
                {
                    "event_type": "completed",
                    "residual": final_residual,
                }
            )

            return SimpleNamespace(return_code=0)

        raise AssertionError("Unexpected additional worker invocation.")

    monkeypatch.setattr(cli, "CheckpointStore", FakeCheckpointStore)
    monkeypatch.setattr(cli, "run_worker", fake_run_worker)

    run_id = "final-verification-test"

    def execute():
        cli.run_cascade(
            worker=worker,
            iterations=100,
            checkpoint_interval=20,
            first_fail_at=55,
            second_fail_at=85,
            corrupt_recovery_checkpoint_at=80,
            run_id=run_id,
            residual_threshold=0.01,
            run_metadata={
                "campaign_id": "verification-test",
                "run_number": 1,
            },
        )

    if expected_success:
        execute()
    else:
        with pytest.raises(typer.Exit) as error:
            execute()

        assert error.value.exit_code == 2

    assert len(calls) == 3

    assert calls[0]["fail_at"] == 55
    assert calls[1]["fail_at"] == 85
    assert calls[1]["corrupt_checkpoint_at"] == 80
    assert calls[2]["fail_at"] is None

    assert calls[1]["resume_from"].name == "state-40.json"
    assert calls[2]["resume_from"].name == "state-60.json"

    run_directory = tmp_path / "results" / "runs" / run_id

    summary = json.loads(
        (run_directory / "summary.json").read_text(encoding="utf-8")
    )

    expected_state = "verified" if expected_success else "unsafe"

    assert summary["success"] is expected_success
    assert summary["final_state"] == expected_state
    assert summary["recovery_count"] == 2
    assert summary["fault_count"] == 2
    assert summary["invalid_checkpoint_count"] == 1

    assert summary["final_checkpoint"] == {
        "attempt_id": 2,
        "checkpoint_id": "ckpt_100",
    }

    assert summary["metrics"]["final_residual"] == pytest.approx(
        final_residual
    )
    assert summary["metrics"]["verification_time_s"] is not None
    assert summary["metrics"]["verification_time_s"] >= 0
    assert summary["metrics"]["total_experiment_time_s"] >= 0

    assert summary["metadata"]["campaign_id"] == "verification-test"

    if expected_success:
        assert summary["failure_reason"] is None
        assert summary["failure_phase"] is None
    else:
        assert summary["failure_reason"]
        assert summary["failure_phase"] == "final_verification"

    events = [
        json.loads(line)
        for line in (run_directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    completed = [
        event
        for event in events
        if event["event_type"] == "run_completed"
    ]

    assert len(completed) == 1
    assert completed[0]["payload"]["final_state"] == expected_state



@pytest.mark.parametrize(
    (
        "failure_mode",
        "expected_phase",
        "reason_fragment",
        "expected_recovery_count",
        "expected_worker_calls",
    ),
    [
        (
            "missing_state",
            "First recovery",
            "Checkpoint state file is missing",
            0,
            1,
        ),
        (
            "first_recovery_exit",
            "First recovery",
            "Expected fault code 42, observed 7",
            1,
            2,
        ),
        (
            "final_recovery_exit",
            "Second recovery",
            "Final recovery worker failed with exit code 7",
            2,
            3,
        ),
    ],
)
def test_recovery_failure_writes_summary(
    tmp_path,
    monkeypatch,
    failure_mode,
    expected_phase,
    reason_fragment,
    expected_recovery_count,
    expected_worker_calls,
) -> None:
    monkeypatch.chdir(tmp_path)

    worker = tmp_path / "fake_worker.exe"
    worker.touch()

    state_path = tmp_path / "checkpoint-state.json"

    if failure_mode != "missing_state":
        state_path.write_text("{}", encoding="utf-8")

    class FakeCheckpointStore:
        def __init__(self, root, run_id):
            self.root = root / run_id
            self.selection_count = 0

        def attempt_directory(self, attempt_id):
            directory = self.root / f"attempt-{attempt_id}"
            directory.mkdir(parents=True, exist_ok=True)
            return directory

        def latest_valid(self):
            self.selection_count += 1

            first_selection = self.selection_count == 1

            return SimpleNamespace(
                metadata=SimpleNamespace(
                    checkpoint_id=(
                        "ckpt_40" if first_selection else "ckpt_60"
                    ),
                    attempt_id=0 if first_selection else 1,
                    iteration=40 if first_selection else 60,
                    residual=0.005,
                    state_path=str(state_path),
                )
            )

    calls = []

    def fake_run_worker(worker_path, **kwargs):
        calls.append(kwargs)
        call_number = len(calls)

        if call_number == 1:
            return SimpleNamespace(return_code=42)

        if call_number == 2:
            return SimpleNamespace(
                return_code=(
                    7 if failure_mode == "first_recovery_exit" else 42
                )
            )

        if call_number == 3 and failure_mode == "final_recovery_exit":
            return SimpleNamespace(return_code=7)

        raise AssertionError("Unexpected worker invocation.")

    monkeypatch.setattr(cli, "CheckpointStore", FakeCheckpointStore)
    monkeypatch.setattr(cli, "run_worker", fake_run_worker)

    run_id = "recovery-failure-test"

    with pytest.raises(typer.Exit) as error:
        cli.run_cascade(
            worker=worker,
            iterations=100,
            checkpoint_interval=20,
            first_fail_at=55,
            second_fail_at=85,
            corrupt_recovery_checkpoint_at=80,
            run_id=run_id,
            run_metadata={
                "campaign_id": "recovery-failure",
                "run_number": 1,
            },
        )

    assert error.value.exit_code == 2
    assert len(calls) == expected_worker_calls

    run_directory = tmp_path / "results" / "runs" / run_id

    summary = json.loads(
        (run_directory / "summary.json").read_text(encoding="utf-8")
    )

    assert summary["success"] is False
    assert summary["final_state"] == "failed"
    assert summary["failure_phase"] == expected_phase
    assert reason_fragment in summary["failure_reason"]
    assert summary["recovery_count"] == expected_recovery_count

    assert summary["metadata"]["campaign_id"] == "recovery-failure"
    assert summary["metrics"]["final_residual"] is None
    assert summary["metrics"]["verification_time_s"] is None
    assert summary["metrics"]["total_experiment_time_s"] >= 0
    assert summary["metrics"]["total_recovery_runtime_s"] >= 0

    events = [
        json.loads(line)
        for line in (run_directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    completed = [
        event
        for event in events
        if event["event_type"] == "run_completed"
    ]

    assert len(completed) == 1
    assert completed[0]["payload"]["final_state"] == "failed"