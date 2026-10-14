from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ScenarioConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WorkerScenario:
    iterations: int
    checkpoint_interval: int
    first_fail_at: int
    second_fail_at: int
    corrupt_recovery_checkpoint_at: int
    residual_threshold: float


@dataclass(frozen=True)
class CampaignScenario:
    run_count: int
    run_id_template: str


@dataclass(frozen=True)
class ScenarioConfig:
    schema_version: int
    scenario_id: str
    description: str
    worker: WorkerScenario
    campaign: CampaignScenario


def load_scenario_config(path: str | Path) -> ScenarioConfig:
    scenario_path = Path(path)

    if not scenario_path.exists():
        raise ScenarioConfigError(
            f"Scenario configuration file does not exist: {scenario_path}"
        )

    with scenario_path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)

    return parse_scenario_config(raw)


def parse_scenario_config(raw: dict[str, Any]) -> ScenarioConfig:
    if not isinstance(raw, dict):
        raise ScenarioConfigError("Scenario root must be a JSON object.")

    if raw.get("schema_version") != 1:
        raise ScenarioConfigError(
            "Unsupported scenario schema_version; expected 1."
        )

    scenario_id = raw.get("scenario_id")
    description = raw.get("description", "")

    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioConfigError("scenario_id must be a non-empty string.")

    worker_raw = raw.get("worker")
    campaign_raw = raw.get("campaign")

    if not isinstance(worker_raw, dict):
        raise ScenarioConfigError("worker must be a JSON object.")

    if not isinstance(campaign_raw, dict):
        raise ScenarioConfigError("campaign must be a JSON object.")

    worker = _parse_worker_scenario(worker_raw)
    campaign = _parse_campaign_scenario(campaign_raw)

    return ScenarioConfig(
        schema_version=1,
        scenario_id=scenario_id,
        description=description,
        worker=worker,
        campaign=campaign,
    )


def _parse_worker_scenario(raw: dict[str, Any]) -> WorkerScenario:
    integer_fields = (
        "iterations",
        "checkpoint_interval",
        "first_fail_at",
        "second_fail_at",
        "corrupt_recovery_checkpoint_at",
    )

    for field in integer_fields:
        if field not in raw:
            raise ScenarioConfigError(f"worker.{field} is required.")

        value = raw[field]

        if not isinstance(value, int) or isinstance(value, bool):
            raise ScenarioConfigError(
                f"worker.{field} must be an integer."
            )

    residual_threshold = raw.get("residual_threshold")

    if not isinstance(residual_threshold, (int, float)) or isinstance(
        residual_threshold,
        bool,
    ):
        raise ScenarioConfigError(
            "worker.residual_threshold must be a number."
        )

    if residual_threshold <= 0:
        raise ScenarioConfigError(
            "worker.residual_threshold must be greater than zero."
        )

    iterations = raw["iterations"]
    checkpoint_interval = raw["checkpoint_interval"]
    first_fail_at = raw["first_fail_at"]
    second_fail_at = raw["second_fail_at"]
    corrupt_recovery_checkpoint_at = raw[
        "corrupt_recovery_checkpoint_at"
    ]

    if checkpoint_interval <= 0:
        raise ScenarioConfigError(
            "worker.checkpoint_interval must be greater than zero."
        )

    if not 0 < first_fail_at < iterations:
        raise ScenarioConfigError(
            "worker.first_fail_at must be between 1 and iterations."
        )

    if not first_fail_at < second_fail_at < iterations:
        raise ScenarioConfigError(
            "worker.second_fail_at must be after first_fail_at "
            "and before iterations."
        )

    if not first_fail_at < corrupt_recovery_checkpoint_at < iterations:
        raise ScenarioConfigError(
            "worker.corrupt_recovery_checkpoint_at must be after "
            "first_fail_at and before iterations."
        )

    return WorkerScenario(
        iterations=iterations,
        checkpoint_interval=checkpoint_interval,
        first_fail_at=first_fail_at,
        second_fail_at=second_fail_at,
        corrupt_recovery_checkpoint_at=corrupt_recovery_checkpoint_at,
        residual_threshold=float(residual_threshold),
    )


def _parse_campaign_scenario(raw: dict[str, Any]) -> CampaignScenario:
    run_count = raw.get("run_count")
    run_id_template = raw.get("run_id_template")

    if not isinstance(run_count, int) or isinstance(run_count, bool):
        raise ScenarioConfigError(
            "campaign.run_count must be an integer."
        )

    if run_count <= 0:
        raise ScenarioConfigError(
            "campaign.run_count must be greater than zero."
        )

    if not isinstance(run_id_template, str) or not run_id_template.strip():
        raise ScenarioConfigError(
            "campaign.run_id_template must be a non-empty string."
        )

    if "{campaign_id}" not in run_id_template:
        raise ScenarioConfigError(
            "campaign.run_id_template must contain {campaign_id}."
        )

    if "{run_number:02d}" not in run_id_template:
        raise ScenarioConfigError(
            "campaign.run_id_template must contain {run_number:02d}."
        )

    return CampaignScenario(
        run_count=run_count,
        run_id_template=run_id_template,
    )


def test_zero_residual_threshold_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid_threshold.json"

    config_path.write_text(
        """
        {
          "schema_version": 1,
          "scenario_id": "invalid_threshold",
          "worker": {
            "iterations": 100,
            "checkpoint_interval": 20,
            "first_fail_at": 55,
            "second_fail_at": 85,
            "corrupt_recovery_checkpoint_at": 80,
            "residual_threshold": 0
          },
          "campaign": {
            "run_count": 1,
            "run_id_template": "{campaign_id}-run-{run_number:02d}"
          }
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ScenarioConfigError):
        load_scenario_config(config_path)