from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CheckpointMetadata:
    checkpoint_id: str
    iteration: int
    residual: float
    checksum: str
    state_path: str
    worker_version: str = "0.1.0"


@dataclass(frozen=True)
class StoredCheckpoint:
    metadata: CheckpointMetadata
    path: Path
    valid: bool
    reason: str


class CheckpointStore:
    def __init__(self, root: str | Path, run_id: str) -> None:
        self.run_directory = Path(root) / run_id
        self.run_directory.mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.run_directory / "manifest.json"

    def write(
        self,
        *,
        checkpoint_id: str,
        iteration: int,
        residual: float,
        checksum_valid: bool,
        state_path: str,
    ) -> CheckpointMetadata:
        payload: dict[str, Any] = {
            "checkpoint_id": checkpoint_id,
            "iteration": iteration,
            "residual": residual,
            "state_path": state_path,
            "worker_version": "0.1.0",
        }

        checksum = self._checksum(self._canonical_json(payload))

        if not checksum_valid:
            checksum = f"corrupted-{checksum}"

        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            iteration=iteration,
            residual=residual,
            checksum=checksum,
            state_path=state_path,
        )

        checkpoint_path = self.run_directory / f"{checkpoint_id}.json"
        checkpoint_path.write_text(
            self._canonical_json(asdict(metadata)),
            encoding="utf-8",
        )

        self._update_manifest(metadata)
        return metadata

    def load_valid_checkpoints(self) -> list[StoredCheckpoint]:
        if not self.manifest_path.exists():
            return []

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        checkpoints: list[StoredCheckpoint] = []

        for checkpoint_id in manifest.get("checkpoints", []):
            checkpoint_path = self.run_directory / f"{checkpoint_id}.json"
            checkpoints.append(self._load_and_validate(checkpoint_path))

        return checkpoints

    def latest_valid(self) -> StoredCheckpoint | None:
        valid_checkpoints = [
            checkpoint
            for checkpoint in self.load_valid_checkpoints()
            if checkpoint.valid
        ]

        if not valid_checkpoints:
            return None

        return max(
            valid_checkpoints,
            key=lambda checkpoint: checkpoint.metadata.iteration,
        )

    def _load_and_validate(self, path: Path) -> StoredCheckpoint:
        if not path.exists():
            return StoredCheckpoint(
                metadata=CheckpointMetadata(
                    checkpoint_id=path.stem,
                    iteration=-1,
                    residual=float("inf"),
                    checksum="missing",
                    state_path="",
                ),
                path=path,
                valid=False,
                reason="checkpoint_file_missing",
            )

        try:
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            metadata = CheckpointMetadata(**raw_data)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            return StoredCheckpoint(
                metadata=CheckpointMetadata(
                    checkpoint_id=path.stem,
                    iteration=-1,
                    residual=float("inf"),
                    checksum="invalid",
                    state_path="",
                ),
                path=path,
                valid=False,
                reason=f"invalid_checkpoint_format: {error}",
            )

        payload = {
            "checkpoint_id": metadata.checkpoint_id,
            "iteration": metadata.iteration,
            "residual": metadata.residual,
            "state_path": metadata.state_path,
            "worker_version": metadata.worker_version,
        }

        expected_checksum = self._checksum(self._canonical_json(payload))

        if metadata.checksum != expected_checksum:
            return StoredCheckpoint(
                metadata=metadata,
                path=path,
                valid=False,
                reason="checksum_mismatch",
            )

        state_file = Path(metadata.state_path)

        if not state_file.exists():
            return StoredCheckpoint(
                metadata=metadata,
                path=path,
                valid=False,
                reason="state_file_missing",
            )

        return StoredCheckpoint(
            metadata=metadata,
            path=path,
            valid=True,
            reason="validated",
        )

    def _update_manifest(self, metadata: CheckpointMetadata) -> None:
        if self.manifest_path.exists():
            manifest = json.loads(
                self.manifest_path.read_text(encoding="utf-8")
            )
        else:
            manifest = {
                "schema_version": 1,
                "checkpoints": [],
            }

        checkpoint_ids: list[str] = manifest["checkpoints"]

        if metadata.checkpoint_id not in checkpoint_ids:
            checkpoint_ids.append(metadata.checkpoint_id)

        checkpoint_ids.sort(
            key=lambda checkpoint_id: int(
                checkpoint_id.removeprefix("ckpt_")
            )
        )

        self.manifest_path.write_text(
            self._canonical_json(manifest),
            encoding="utf-8",
        )

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _checksum(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()