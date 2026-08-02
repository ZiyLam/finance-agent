param(
    [string]$Distro = "Ubuntu-26.04",
    [string]$SecretFile = "G:\Program Files\finance-agent-api-token-backup.txt"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Purpose: normalize and secure the human-maintained source before WSL or
# Kubernetes receives any value.
& (Join-Path $PSScriptRoot "normalize_local_secret_file.ps1") -SecretFile $SecretFile
if ($LASTEXITCODE -ne 0) {
    throw "Local credential-file normalization failed."
}

# Purpose: convert Windows paths explicitly so spaces and drive letters are not
# interpreted as Linux path syntax.
$wslProjectRoot = (& wsl.exe -d $Distro -e wslpath -a $projectRoot).Trim()
$wslSecretFile = (& wsl.exe -d $Distro -e wslpath -a $SecretFile).Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslProjectRoot -or -not $wslSecretFile) {
    throw "Could not resolve the project or credential path inside WSL."
}

# Purpose: create the complete Kubernetes Secret without exposing values on the
# command line, in generated YAML, or in this script's output.
& wsl.exe -d $Distro --cd $wslProjectRoot -e bash scripts/sync_kind_secrets.sh $wslSecretFile
if ($LASTEXITCODE -ne 0) {
    throw "Kubernetes credential synchronization failed."
}

# Purpose: environment-variable secrets are read at process startup, so a
# controlled rollout is required after replacement.
$replicas = (& wsl.exe -d $Distro -e kubectl --context kind-finance-agent `
    --namespace finance-agent-staging get deployment finance-agent `
    -o 'jsonpath={.spec.replicas}').Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Finance Agent deployment."
}
if ($replicas -eq "0") {
    Write-Host "Credentials synchronized. Deployment is stopped; the next start will load them."
    exit 0
}

& wsl.exe -d $Distro -e kubectl --context kind-finance-agent `
    --namespace finance-agent-staging rollout restart deployment/finance-agent
if ($LASTEXITCODE -ne 0) {
    throw "Could not restart the Finance Agent deployment."
}
& wsl.exe -d $Distro -e kubectl --context kind-finance-agent `
    --namespace finance-agent-staging rollout status deployment/finance-agent --timeout=180s
if ($LASTEXITCODE -ne 0) {
    throw "Finance Agent did not become ready after credential synchronization."
}

# Purpose: verify from the Windows client path, not only inside Kubernetes. The
# token is read in memory and never printed.
$webTokenPath = Join-Path $projectRoot ".local\kind-web-access-token"
$webToken = ([IO.File]::ReadAllText($webTokenPath, [Text.Encoding]::UTF8)).Trim()
$headers = @{ "X-Finance-Agent-Token" = $webToken }
$status = Invoke-RestMethod -Uri "http://localhost:18080/v1/web/status" -Headers $headers -TimeoutSec 15
$catalog = Invoke-RestMethod -Uri "http://localhost:18080/v1/web/sources" -Headers $headers -TimeoutSec 15
$dataSourceCount = @($catalog.sources | Where-Object { $_.configuration_group -eq "data_source" }).Count
$llmCount = @($catalog.sources | Where-Object { $_.configuration_group -eq "llm" }).Count
if (-not $status -or $dataSourceCount -lt 1 -or $llmCount -lt 1) {
    throw "Credential synchronization completed, but the deployed settings catalog failed verification."
}
Write-Host "Credential synchronization verified from Windows: $dataSourceCount data sources, $llmCount LLM provider(s)."
