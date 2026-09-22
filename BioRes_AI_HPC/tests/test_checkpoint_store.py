from pathlib import Path

from biores_ai_hpc.checkpoint_store import CheckpointStore


def write_state_file(path: Path, iteration: int, residual: float) -> None:
    path.write_text(
        f"iteration={iteration}\nresidual={residual}\n",
        encoding="utf-8",
    )


def test_latest_valid_checkpoint_is_selected(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "run-001")

    state_20 = store.run_directory / "ckpt_20.state"
    state_40 = store.run_directory / "ckpt_40.state"

    write_state_file(state_20, iteration=20, residual=0.35)
    write_state_file(state_40, iteration=40, residual=0.12)

    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_20",
        iteration=20,
        residual=0.35,
        checksum_valid=True,
        state_path=str(state_20),
    )
    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_40",
        iteration=40,
        residual=0.12,
        checksum_valid=True,
        state_path=str(state_40),
    )

    checkpoint = store.latest_valid()

    assert checkpoint is not None
    assert checkpoint.valid
    assert checkpoint.metadata.checkpoint_id == "ckpt_40"
    assert checkpoint.metadata.iteration == 40
    assert checkpoint.metadata.state_path == str(state_40)


def test_corrupted_checkpoint_is_ignored(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "run-002")

    state_20 = store.run_directory / "ckpt_20.state"
    state_40 = store.run_directory / "ckpt_40.state"

    write_state_file(state_20, iteration=20, residual=0.35)
    write_state_file(state_40, iteration=40, residual=0.12)

    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_20",
        iteration=20,
        residual=0.35,
        checksum_valid=True,
        state_path=str(state_20),
    )
    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_40",
        iteration=40,
        residual=0.12,
        checksum_valid=False,
        state_path=str(state_40),
    )

    checkpoint = store.latest_valid()

    assert checkpoint is not None
    assert checkpoint.valid
    assert checkpoint.metadata.checkpoint_id == "ckpt_20"
    assert checkpoint.metadata.iteration == 20


def test_checkpoint_with_missing_state_file_is_rejected(
    tmp_path: Path,
) -> None:
    store = CheckpointStore(tmp_path, "run-003")

    missing_state = store.run_directory / "ckpt_20.state"

    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_20",
        iteration=20,
        residual=0.35,
        checksum_valid=True,
        state_path=str(missing_state),
    )

    assert store.latest_valid() is None


def test_no_valid_checkpoint_returns_none(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "run-004")

    state_20 = store.run_directory / "ckpt_20.state"
    write_state_file(state_20, iteration=20, residual=0.35)

    store.write(
        attempt_id=0,
        checkpoint_id="ckpt_20",
        iteration=20,
        residual=0.35,
        checksum_valid=False,
        state_path=str(state_20),
    )

    assert store.latest_valid() is None