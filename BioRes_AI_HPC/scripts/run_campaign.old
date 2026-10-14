[CmdletBinding()]
param(
    [string]$CampaignId = "campaign-001",
    [int]$RunCount = 3,
    [string]$Worker = ".\build\cpp\Release\biores_worker.exe",
    [int]$Iterations = 100,
    [int]$CheckpointInterval = 20,
    [int]$FirstFailAt = 55,
    [int]$SecondFailAt = 85,
    [int]$CorruptRecoveryCheckpointAt = 80,
    [switch]$CleanCampaignArtifacts
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path $Worker)) {
    throw "Worker executable was not found: $Worker"
}

$runIds = 1..$RunCount | ForEach-Object {
    "{0}-run-{1:D2}" -f $CampaignId, $_
}

if ($CleanCampaignArtifacts) {
    foreach ($runId in $runIds) {
        Remove-Item `
            -Recurse `
            -Force `
            (Join-Path "results\checkpoints" $runId) `
            -ErrorAction SilentlyContinue

        Remove-Item `
            -Recurse `
            -Force `
            (Join-Path "results\runs" $runId) `
            -ErrorAction SilentlyContinue
    }
}

foreach ($runId in $runIds) {
    Write-Host ""
    Write-Host "=== Starting $runId ===" -ForegroundColor Cyan

    & biores run-cascade `
        --worker $Worker `
        --iterations $Iterations `
        --checkpoint-interval $CheckpointInterval `
        --first-fail-at $FirstFailAt `
        --second-fail-at $SecondFailAt `
        --corrupt-recovery-checkpoint-at $CorruptRecoveryCheckpointAt `
        --run-id $runId

    if ($LASTEXITCODE -ne 0) {
        throw "Run failed: $runId (exit code $LASTEXITCODE)"
    }
}

$csvOutput = "results\reports\${CampaignId}_runs_summary.csv"
$campaignSummaryOutput = "results\reports\${CampaignId}_summary.json"
$reportOutput = "results\reports\${CampaignId}_report.md"

Write-Host ""
Write-Host "=== Exporting campaign CSV ===" -ForegroundColor Cyan

& biores export-runs-csv `
    --runs-root ".\results\runs" `
    --run-prefix "${CampaignId}-" `
    --output $csvOutput

if ($LASTEXITCODE -ne 0) {
    throw "CSV export failed (exit code $LASTEXITCODE)"
}

Write-Host ""
Write-Host "=== Analyzing campaign ===" -ForegroundColor Cyan

& biores analyze-runs `
    --input $csvOutput `
    --output $campaignSummaryOutput

if ($LASTEXITCODE -ne 0) {
    throw "Campaign analysis failed (exit code $LASTEXITCODE)"
}

Write-Host ""
Write-Host "=== Generating Markdown report ===" -ForegroundColor Cyan

& biores generate-report `
    --input-csv $csvOutput `
    --campaign-summary $campaignSummaryOutput `
    --output $reportOutput

if ($LASTEXITCODE -ne 0) {
    throw "Report generation failed (exit code $LASTEXITCODE)"
}

Write-Host ""
Write-Host "Campaign completed successfully." -ForegroundColor Green
Write-Host "CSV report: $csvOutput"
Write-Host "JSON report: $campaignSummaryOutput"
Write-Host "Markdown report: $reportOutput"