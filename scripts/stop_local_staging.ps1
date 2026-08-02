param(
    [string]$Distro = "Ubuntu-26.04"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$keepalivePidFile = Join-Path $projectRoot ".local\wsl-keepalive.pid"

& wsl.exe -d $Distro -e kubectl --context kind-finance-agent --namespace finance-agent-staging `
    scale deployment/finance-agent --replicas=0
if ($LASTEXITCODE -ne 0) {
    Write-Warning "The Staging deployment could not be scaled down cleanly."
}

if (Test-Path -LiteralPath $keepalivePidFile) {
    $keepalivePid = [int](Get-Content -LiteralPath $keepalivePidFile -Raw)
    Stop-Process -Id $keepalivePid -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $keepalivePidFile -Force
}

Write-Host "Finance Agent Staging has been stopped."
