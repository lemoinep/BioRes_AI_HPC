[CmdletBinding()]
param(
    [string]$CampaignId = "campaign-001",
    [string]$ScenarioConfig = ".\configs\cascade_corruption.json",
    [string]$Worker = ".\build\cpp\Release\biores_worker.exe",
    [switch]$CleanCampaignArtifacts
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not (Test-Path $ScenarioConfig)) {
    throw "Scenario configuration file was not found: $ScenarioConfig"
}

if (-not (Test-Path $Worker)) {
    throw "Worker executable was not found: $Worker"
}

$scenario = Get-Content $ScenarioConfig -Raw | ConvertFrom-Json

$runCount = $scenario.campaign.run_count
$runIdTemplate = $scenario.campaign.run_id_template

$runIds = 1..$runCount | ForEach-Object {
    $runNumber = $_

    $runIdTemplate `
        -replace "\{campaign_id\}", $CampaignId `
        -replace "\{run_number:02d\}", ("{0:D2}" -f $runNumber)
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

$csvOutput = "results\reports\${CampaignId}_runs_summary.csv"
$campaignSummaryOutput = "results\reports\${CampaignId}_summary.json"
$reportOutput = "results\reports\${CampaignId}_report.md"

$runNumber = 0

foreach ($runId in $runIds) {
    $runNumber++

    Write-Host ""
    Write-Host "=== Starting $runId ===" -ForegroundColor Cyan

    & biores run-scenario `
        --config $ScenarioConfig `
        --campaign-id $CampaignId `
        --run-number $runNumber `
        --worker $Worker

    if ($LASTEXITCODE -ne 0) {
        throw "Run failed: $runId (exit code $LASTEXITCODE)"
    }
}

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
Write-Host "Scenario: $ScenarioConfig"
Write-Host "CSV report: $csvOutput"
Write-Host "JSON report: $campaignSummaryOutput"
Write-Host "Markdown report: $reportOutput"