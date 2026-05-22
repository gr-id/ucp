# Deploy UCP+AP2 2nd PoC to Cloud Run + Firebase Hosting.
#
# Usage (one-time):
#   .\scripts\deploy.ps1 -InitSecret
# Subsequent deploys:
#   .\scripts\deploy.ps1
#
# Prerequisites:
#   - gcloud CLI installed
#   - firebase CLI installed
#   - GCP project `ucp-poc` already exists (Firebase console)
#   - Local .env has SERPAPI_KEY

param(
    [switch]$InitSecret = $false,
    [string]$Project = "ucp-poc",
    [string]$Region = "asia-northeast3",        # Seoul
    [string]$Service = "ucp-poc",
    [string]$Secret = "serpapi-key"
)

$ErrorActionPreference = "Stop"

# Refresh PATH so gcloud / firebase resolve in the current shell.
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" +
            [System.Environment]::GetEnvironmentVariable("PATH","Machine")

Write-Host "==> using project: $Project (region $Region)"
gcloud config set project $Project

if ($InitSecret) {
    Write-Host "==> enabling required services"
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

    Write-Host "==> reading SERPAPI_KEY from local .env"
    if (-not (Test-Path .env)) { throw ".env not found in repo root" }
    $line = (Get-Content .env | Where-Object { $_ -match '^SERPAPI_KEY=' } | Select-Object -First 1)
    if (-not $line) { throw "SERPAPI_KEY missing in .env" }
    $serpKey = $line -replace '^SERPAPI_KEY=', ''
    $serpKey = $serpKey.Trim().Trim('"').Trim("'")

    $existing = gcloud secrets list --filter="name~$Secret" --format="value(name)" 2>$null
    if ($existing) {
        Write-Host "==> updating existing secret $Secret"
        $serpKey | gcloud secrets versions add $Secret --data-file=-
    } else {
        Write-Host "==> creating secret $Secret"
        $serpKey | gcloud secrets create $Secret --data-file=-
    }

    Write-Host "==> granting Cloud Run service account access to the secret"
    $projectNumber = (gcloud projects describe $Project --format="value(projectNumber)")
    $sa = "$projectNumber-compute@developer.gserviceaccount.com"
    gcloud secrets add-iam-policy-binding $Secret `
        --member="serviceAccount:$sa" `
        --role="roles/secretmanager.secretAccessor" | Out-Null
}

Write-Host "==> deploying to Cloud Run as `"$Service`""
gcloud run deploy $Service `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --port 8080 `
    --memory 1Gi `
    --cpu 1 `
    --min-instances 0 `
    --max-instances 2 `
    --timeout 3600 `
    --session-affinity `
    --set-env-vars UCP_CATALOG_MODE=serpapi `
    --set-secrets "SERPAPI_KEY=${Secret}:latest"

$url = gcloud run services describe $Service --region $Region --format="value(status.url)"
Write-Host ""
Write-Host "Cloud Run URL: $url"
Write-Host ""
Write-Host "Next: firebase deploy --only hosting"
