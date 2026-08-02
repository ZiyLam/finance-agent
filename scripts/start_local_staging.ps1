param(
    [string]$Distro = "Ubuntu-26.04"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localState = Join-Path $projectRoot ".local"
$keepalivePidFile = Join-Path $localState "wsl-keepalive.pid"
New-Item -ItemType Directory -Path $localState -Force | Out-Null

$keepaliveProcess = $null
if (Test-Path -LiteralPath $keepalivePidFile) {
    $existingPid = [int](Get-Content -LiteralPath $keepalivePidFile -Raw)
    $keepaliveProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
}

if (-not $keepaliveProcess) {
    $keepaliveArgs = @("-d", $Distro, "-e", "sleep", "infinity")
    $keepaliveProcess = Start-Process -FilePath "wsl.exe" -ArgumentList $keepaliveArgs `
        -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    if ($keepaliveProcess.HasExited) {
        throw "The WSL keepalive process exited before Staging could start."
    }
    Set-Content -LiteralPath $keepalivePidFile -Value $keepaliveProcess.Id -NoNewline
}

$wslProjectRoot = (& wsl.exe -d $Distro -e wslpath -a $projectRoot).Trim()
if ($LASTEXITCODE -ne 0 -or -not $wslProjectRoot) {
    throw "Could not resolve the project path inside WSL."
}

& wsl.exe -d $Distro --cd $wslProjectRoot -e bash scripts/deploy_local_kind.sh
if ($LASTEXITCODE -ne 0) {
    throw "Local Staging deployment failed."
}

Write-Host "Finance Agent Staging is running at http://localhost:18080/web/"
Write-Host "Keepalive PID: $($keepaliveProcess.Id)"
