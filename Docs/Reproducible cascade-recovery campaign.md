## Reproducible cascade-recovery campaign

The repository includes an automated workflow for running an isolated, repeatable cascade-recovery campaign.

### Scenario

Each run executes a deterministic 100-iteration worker workload with persistent checkpoints every 20 iterations:

1. The worker writes valid checkpoints at iterations 20 and 40.
2. A controlled worker termination is injected at iteration 55.
3. Recovery attempt 1 restores the latest valid checkpoint, `ckpt_40`.
4. The resumed worker writes `ckpt_60`.
5. The recovery checkpoint at iteration 80 is deliberately corrupted.
6. A second controlled worker termination is injected at iteration 85.
7. Recovery attempt 2 rejects the corrupted `ckpt_80`, restores `ckpt_60`, and resumes execution.
8. The final attempt writes valid `ckpt_80` and `ckpt_100`.
9. The controller performs integrity and numerical verification and reaches `verified`.

### Run a campaign

From the repository root:

```powershell
.\scripts\run_campaign.ps1 `
  -CampaignId campaign-001 `
  -RunCount 3 `
  -CleanCampaignArtifacts
```

If local PowerShell scripts are blocked for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then rerun the campaign command. The `Process` scope affects only the active PowerShell session. [1]

### Campaign isolation

The campaign ID is incorporated into each run ID:

```text
campaign-001-run-01
campaign-001-run-02
campaign-001-run-03
```

The campaign script exports only runs whose ID begins with:

```text
campaign-001-
```

This prevents historical runs, such as `summary-001`, from being mixed into a campaign report.

### Generated artifacts

A three-run campaign produces:

```text
results/
├── checkpoints/
│   ├── campaign-001-run-01/
│   │   ├── attempt-0/
│   │   ├── attempt-1/
│   │   ├── attempt-2/
│   │   └── manifest.json
│   ├── campaign-001-run-02/
│   └── campaign-001-run-03/
│
├── runs/
│   ├── campaign-001-run-01/
│   │   ├── events.jsonl
│   │   └── summary.json
│   ├── campaign-001-run-02/
│   └── campaign-001-run-03/
│
└── reports/
    ├── campaign-001_runs_summary.csv
    ├── campaign-001_summary.json
    └── campaign-001_report.md
```

- `manifest.json` indexes checkpoint metadata, checksums, state-file paths, and attempt provenance.
- `events.jsonl` is the append-only event journal for a run.
- `summary.json` is the per-run derived summary.
- `campaign-001_runs_summary.csv` contains one row per run.
- `campaign-001_summary.json` contains campaign-level metrics.
- `campaign-001_report.md` is a Markdown report suitable for review or publication.

### Inspect results

```powershell
Import-Csv .\results\reports\campaign-001_runs_summary.csv |
    Select-Object run_id, success, final_state,
        fault_count, recovery_count,
        invalid_checkpoint_count,
        final_checkpoint_id,
        total_experiment_time_s |
    Format-Table -AutoSize
```

View the campaign report:

```powershell
Get-Content .\results\reports\campaign-001_report.md
```

### Expected outcome

For the standard three-run cascade scenario:

- All runs should finish with `final_state = verified`.
- Every run should contain two injected faults and two recovery attempts.
- One deliberately corrupted checkpoint should be rejected per run.
- The final checkpoint should be `ckpt_100`.
- The campaign summary should report three successful runs, six injected faults, six recoveries, and three rejected checkpoints.