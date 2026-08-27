from pathlib import Path

from biores_ai_hpc.cpp_bridge import run_worker


def test_worker_completes_without_fault(worker_path: Path) -> None:
    result = run_worker(
        worker_path,
        iterations=10,
        checkpoint_interval=5,
    )

    assert result.return_code == 0
    assert result.events[-1]["event_type"] == "completed"


def test_worker_injects_expected_fault(worker_path: Path) -> None:
    result = run_worker(
        worker_path,
        iterations=10,
        checkpoint_interval=5,
        fail_at=7,
    )

    assert result.return_code == 42
    assert result.events[-1]["event_type"] == "fault_injected"