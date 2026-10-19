## Declarative resilience scenarios

BioRes_AI_HPC supports JSON-based scenarios that configure worker execution,
fault injection, checkpoint corruption, final verification, and campaign runs.

Example: `configs/cascade_corruption.json`

```json
{
  "schema_version": 1,
  "scenario_id": "cascade_corruption",
  "description": "Cascade recovery after worker termination and checkpoint corruption.",
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
```

This scenario exercises the following recovery sequence:

1. The worker creates checkpoints at iterations 20 and 40.
2. A first worker termination is injected at iteration 55.
3. Execution resumes from the valid checkpoint `ckpt_40`.
4. The worker creates `ckpt_60`, then checkpoint `ckpt_80` is deliberately corrupted.
5. A second worker termination is injected at iteration 85.
6. Recovery selects `ckpt_60` rather than the corrupted `ckpt_80`.
7. Execution regenerates valid checkpoints at iterations 80 and 100.
8. The recovered state undergoes integrity and numerical verification.

The `residual_threshold` parameter configures the residual threshold used
during final verification.

## Running an experiment

From the repository root, with the Python environment activated and the
C++ worker already built:

```powershell
biores run-scenario `
  --config .\configs\cascade_corruption.json `
  --campaign-id campaign-001 `
  --run-number 1 `
  --worker .\build\cpp\Release\biores_worker.exe
```

A successful execution ends with:

```text
Final state: verified
Recovered state satisfies integrity and numerical checks.
```

## Running a campaign

The PowerShell script reads the run count and run identifier template
from the scenario configuration, executes the runs, and generates
campaign-level reports.

```powershell
.\scripts\run_campaign.ps1 `
  -CampaignId campaign-001 `
  -ScenarioConfig .\configs\cascade_corruption.json `
  -CleanCampaignArtifacts
```

Warning: `-CleanCampaignArtifacts` deletes existing checkpoint and run
directories for the run identifiers generated for this campaign.
Use a new campaign identifier to preserve previous experiment results.

For a single-run smoke test:

```powershell
.\scripts\run_campaign.ps1 `
  -CampaignId campaign-smoke `
  -ScenarioConfig .\configs\cascade_single_run.json `
  -CleanCampaignArtifacts
```

## Outputs and reporting

The campaign workflow is:

```text
JSON scenario
  → run execution and recovery
  → per-run events and summaries
  → campaign-scoped CSV export
  → aggregated JSON analysis
  → Markdown report
```

For `campaign-001`, the output layout is:

```text
results/
├── checkpoints/
│   ├── campaign-001-run-01/
│   ├── campaign-001-run-02/
│   └── campaign-001-run-03/
├── runs/
│   ├── campaign-001-run-01/
│   │   ├── events.jsonl
│   │   └── summary.json
│   ├── campaign-001-run-02/
│   └── campaign-001-run-03/
└── reports/
    ├── campaign-001_runs_summary.csv
    ├── campaign-001_summary.json
    └── campaign-001_report.md
```

PowerShell orchestrates campaigns. Python validates scenario configurations,
coordinates execution and recovery, and generates campaign reports.
The C++ worker performs the simulated computation.

## Validated example: cascade corruption

A local three-run campaign produced the following results:

| Run | Success | Final state | Injected terminations | Recoveries | Invalid checkpoints | Final checkpoint |
|---|---|---|---:|---:|---:|---|
| campaign-001-run-01 | True | verified | 2 | 2 | 1 | ckpt_100 |
| campaign-001-run-02 | True | verified | 2 | 2 | 1 | ckpt_100 |
| campaign-001-run-03 | True | verified | 2 | 2 | 1 | ckpt_100 |

All three runs completed successfully under this scenario.

These results demonstrate the tested local recovery sequence. They do not
establish production readiness, distributed fault tolerance, or performance
on real AI/HPC workloads.

## Tests

Run the test suite:

```powershell
pytest -q
```

At this validation milestone, the local suite completed with:

```text
22 passed
```

Scenario tests include loading a valid residual threshold and rejecting
a zero residual threshold.