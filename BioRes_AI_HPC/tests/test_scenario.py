import pytest

from biores_ai_hpc.scenario import (
    ScenarioConfigError,
    load_scenario_config,
)


def test_load_valid_scenario_config(tmp_path) -> None:
    config_path = tmp_path / "cascade_corruption.json"

    config_path.write_text(
        """
        {
          "schema_version": 1,
          "scenario_id": "cascade_corruption",
          "description": "Cascade recovery scenario.",
          "worker": {
            "iterations": 100,
            "checkpoint_interval": 20,
            "first_fail_at": 55,
            "second_fail_at": 85,
            "corrupt_recovery_checkpoint_at": 80,
            "residual_threshold": 0.01
          },
          "campaign": {
            "run_count": 3,
            "run_id_template": "{campaign_id}-run-{run_number:02d}"
          }
        }
        """,
        encoding="utf-8",
    )

    config = load_scenario_config(config_path)

    assert config.schema_version == 1
    assert config.scenario_id == "cascade_corruption"
    assert config.worker.iterations == 100
    assert config.worker.checkpoint_interval == 20
    assert config.worker.first_fail_at == 55
    assert config.worker.second_fail_at == 85
    assert config.worker.corrupt_recovery_checkpoint_at == 80
    assert config.campaign.run_count == 3
    assert config.worker.residual_threshold == 0.01
    assert (
        config.campaign.run_id_template
        == "{campaign_id}-run-{run_number:02d}"
    )


def test_missing_scenario_file_is_rejected(tmp_path) -> None:
    with pytest.raises(ScenarioConfigError):
        load_scenario_config(tmp_path / "missing.json")


def test_invalid_schema_version_is_rejected(tmp_path) -> None:
    config_path = tmp_path / "invalid.json"

    config_path.write_text(
        '{"schema_version": 2, "scenario_id": "x"}',
        encoding="utf-8",
    )

    with pytest.raises(ScenarioConfigError):
        load_scenario_config(config_path)


def test_second_fail_must_come_after_first_fail(tmp_path) -> None:
    config_path = tmp_path / "invalid_order.json"

    config_path.write_text(
        """
        {
          "schema_version": 1,
          "scenario_id": "invalid_order",
          "worker": {
            "iterations": 100,
            "checkpoint_interval": 20,
            "first_fail_at": 85,
            "second_fail_at": 55,
            "corrupt_recovery_checkpoint_at": 80,
            "residual_threshold": 0.01
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
