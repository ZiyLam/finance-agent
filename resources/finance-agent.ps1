[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AgentArguments
)

$codexRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtimePython = Join-Path $codexRoot '.venv\Scripts\finance-agent.exe'
$cacheDirectory = Join-Path $PSScriptRoot 'cache\yfinance'

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw "The shared Codex runtime is missing. From the project directory, run: & 'G:\Program Files\Codex\.venv\Scripts\python.exe' -m pip install -e ."
}

New-Item -ItemType Directory -Force -Path $cacheDirectory | Out-Null
$env:YFINANCE_CACHE_DIR = $cacheDirectory
& $runtimePython @AgentArguments
exit $LASTEXITCODE
