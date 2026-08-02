param(
    [string]$SecretFile = "G:\Program Files\finance-agent-api-token-backup.txt",
    [string]$ContractFile = ""
)

$ErrorActionPreference = "Stop"

# Purpose: resolve the repository-owned blank template without depending on
# the caller's current directory.
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ContractFile) {
    $ContractFile = Join-Path $projectRoot "config\external-secrets.env.example"
}
$resolvedContract = (Resolve-Path -LiteralPath $ContractFile).Path
$resolvedSecret = (Resolve-Path -LiteralPath $SecretFile).Path
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

function Protect-CredentialAcl {
    param([string]$Path)

    # Purpose: remove inherited read access before any plaintext is written.
    & icacls.exe $Path /inheritance:r /grant:r `
        "$($currentIdentity):(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The credential-file Windows ACL could not be restricted: $Path"
    }
}

function Read-CredentialRecords {
    param(
        [string[]]$Lines,
        [System.Collections.Generic.HashSet[string]]$AllowedKeys,
        [switch]$ReadingContract
    )

    $records = [ordered]@{}
    for ($index = 0; $index -lt $Lines.Length; $index++) {
        $line = $Lines[$index]
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\s*#') {
            continue
        }
        if ($line -notmatch '^([A-Z][A-Z0-9_]*)=(.*)$') {
            throw "Invalid credential record at line $($index + 1). Use KEY=VALUE without export, quotes, or spaces."
        }
        $key = $matches[1]
        $value = $matches[2]
        if ($records.Contains($key)) {
            throw "Duplicate credential key at line $($index + 1): $key"
        }
        if (-not $ReadingContract -and -not $AllowedKeys.Contains($key)) {
            throw "Unknown credential key at line $($index + 1): $key"
        }
        if ($value -ne $value.Trim()) {
            throw "Credential value has leading or trailing whitespace at line $($index + 1): $key"
        }
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            throw "Credential values must not be wrapped in quotes at line $($index + 1): $key"
        }
        $records[$key] = $value
    }
    return $records
}

# Purpose: the committed template is the allow-list and canonical key order.
$contractLines = [IO.File]::ReadAllLines($resolvedContract, $utf8)
$emptyAllowList = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
$contractRecords = Read-CredentialRecords -Lines $contractLines -AllowedKeys $emptyAllowList -ReadingContract
$allowedKeys = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach ($key in $contractRecords.Keys) {
    [void]$allowedKeys.Add($key)
}

# Purpose: validate the current file before writing anything, so a typo cannot
# silently remove or rename a real credential.
Protect-CredentialAcl -Path $resolvedSecret
$sourceLines = [IO.File]::ReadAllLines($resolvedSecret, $utf8)
$sourceRecords = Read-CredentialRecords -Lines $sourceLines -AllowedKeys $allowedKeys

# Purpose: merge existing values into the blank template. Missing optional keys
# remain visibly blank, making future maintenance predictable.
$normalizedLines = foreach ($line in $contractLines) {
    if ($line -match '^([A-Z][A-Z0-9_]*)=') {
        $key = $matches[1]
        $value = if ($sourceRecords.Contains($key)) { $sourceRecords[$key] } else { "" }
        "$key=$value"
    }
    else {
        $line
    }
}
$normalizedText = ($normalizedLines -join "`r`n") + "`r`n"
$temporaryPath = "$resolvedSecret.$([Guid]::NewGuid().ToString('N')).tmp"
$rollbackPath = "$resolvedSecret.$([Guid]::NewGuid().ToString('N')).rollback"

try {
    # Purpose: write and strictly re-read a same-directory temporary file before
    # atomically replacing the user's credential bundle.
    [IO.File]::WriteAllBytes($temporaryPath, [byte[]]@())
    Protect-CredentialAcl -Path $temporaryPath
    [IO.File]::WriteAllText($temporaryPath, $normalizedText, $utf8)
    $roundTripLines = [IO.File]::ReadAllLines($temporaryPath, $utf8)
    $roundTripRecords = Read-CredentialRecords -Lines $roundTripLines -AllowedKeys $allowedKeys
    foreach ($key in $sourceRecords.Keys) {
        if (-not $roundTripRecords.Contains($key) -or $roundTripRecords[$key] -cne $sourceRecords[$key]) {
            throw "Credential normalization verification failed for key: $key"
        }
    }
    [IO.File]::Replace($temporaryPath, $resolvedSecret, $rollbackPath, $true)
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
    if (Test-Path -LiteralPath $rollbackPath) {
        Remove-Item -LiteralPath $rollbackPath -Force
    }
}

# Purpose: assert the replacement retained the restricted ACL.
Protect-CredentialAcl -Path $resolvedSecret

$configuredCount = @($roundTripRecords.GetEnumerator() | Where-Object { $_.Value }).Count
$missingCount = $roundTripRecords.Count - $configuredCount
Write-Host "Credential file normalized without displaying values: $resolvedSecret"
Write-Host "Configured keys: $configuredCount; blank optional keys: $missingCount"
