[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$runtimePython = Join-Path $PSScriptRoot 'data-source-runtime\Scripts\finance-agent.exe'
$cacheDirectory = Join-Path $PSScriptRoot 'cache\yfinance'

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw "The project data-source runtime is missing. Recreate it using resources\\README.md."
}

New-Item -ItemType Directory -Force -Path $cacheDirectory | Out-Null
$env:YFINANCE_CACHE_DIR = $cacheDirectory
& $runtimePython @Arguments
exit $LASTEXITCODE
