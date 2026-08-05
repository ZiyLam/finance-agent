param(
    [string]$CsvFile = "C:\Users\Ziy Lam\Desktop\默认业务空间-apiKey-6432087.csv",
    [string]$SecretFile = "G:\Program Files\finance-agent-api-token-backup.txt",
    [string]$ContractFile = "",
    [string]$ConfigMapFile = ""
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $ContractFile) {
    $ContractFile = Join-Path $projectRoot "config\external-secrets.env.example"
}
if (-not $ConfigMapFile) {
    $ConfigMapFile = Join-Path $projectRoot "deploy\kubernetes\configmap.yaml"
}
$resolvedCsv = (Resolve-Path -LiteralPath $CsvFile).Path
$resolvedSecret = (Resolve-Path -LiteralPath $SecretFile).Path
$resolvedContract = (Resolve-Path -LiteralPath $ContractFile).Path
$resolvedConfigMap = (Resolve-Path -LiteralPath $ConfigMapFile).Path
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

function Protect-CredentialAcl {
    param([string]$Path)

    # Purpose: keep the temporary and final plaintext files readable only by
    # the current user, SYSTEM, and local administrators.
    & icacls.exe $Path /inheritance:r /grant:r `
        "$($currentIdentity):(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The credential-file Windows ACL could not be restricted."
    }
}

try {
    # Purpose: decode the user-provided CSV strictly and identify the one
    # DashScope-shaped key without displaying any cell value.
    $csvText = [IO.File]::ReadAllText($resolvedCsv, $utf8)
    $rows = @($csvText | ConvertFrom-Csv)
    if ($rows.Count -eq 0) {
        throw "The Bailian CSV contains no data rows."
    }
    $columns = @($rows[0].PSObject.Properties.Name)
    $credentialColumns = @($columns | Where-Object { $_ -ne "id" })
    if ($credentialColumns.Count -ne 1) {
        throw "The Bailian CSV must contain one credential column besides id."
    }
    $credentialColumn = $credentialColumns[0]
    $workspaceId = [string]$credentialColumn
    if ($workspaceId -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') {
        throw "The CSV credential-column header is not a valid Bailian workspace identifier."
    }
    $candidates = @(
        $rows |
            ForEach-Object { [string]($_.$credentialColumn).Trim() } |
            Where-Object { $_ -match '^sk-\S+$' }
    )
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one Bailian API key shaped as sk-...; found $($candidates.Count)."
    }
    $selectedApiKey = [string]$candidates[0]

    # Purpose: fail closed when the CSV belongs to a different business space
    # than the declarative Kubernetes ConfigMap currently targets.
    $configMapText = [IO.File]::ReadAllText($resolvedConfigMap, $utf8)
    if ($configMapText -notmatch '(?m)^\s*BAILIAN_WORKSPACE_ID:\s*"([^"]+)"\s*$') {
        throw "BAILIAN_WORKSPACE_ID is missing from the Kubernetes ConfigMap."
    }
    $configuredWorkspaceId = [string]$matches[1]
    if ($configuredWorkspaceId -cne $workspaceId) {
        throw "CSV workspace identifier differs from the Kubernetes ConfigMap; update the non-secret ConfigMap first."
    }

    # Purpose: replace only BAILIAN_API_KEY in the authority file, then let the
    # canonical normalizer restore key order and strict formatting.
    $contractText = [IO.File]::ReadAllText($resolvedContract, $utf8)
    if ($contractText -notmatch '(?m)^BAILIAN_API_KEY=') {
        throw "The committed credential contract does not contain BAILIAN_API_KEY."
    }
    Protect-CredentialAcl -Path $resolvedSecret
    $sourceLines = [IO.File]::ReadAllLines($resolvedSecret, $utf8)
    $found = $false
    $updatedLines = foreach ($line in $sourceLines) {
        if ($line -match '^BAILIAN_API_KEY=') {
            if ($found) { throw "The authority file contains duplicate BAILIAN_API_KEY records." }
            $found = $true
            "BAILIAN_API_KEY=$selectedApiKey"
        }
        else {
            $line
        }
    }
    if (-not $found) {
        $updatedLines += "BAILIAN_API_KEY=$selectedApiKey"
    }
    $updatedText = ($updatedLines -join "`r`n") + "`r`n"
    $temporaryPath = "$resolvedSecret.$([Guid]::NewGuid().ToString('N')).tmp"
    $rollbackPath = "$resolvedSecret.$([Guid]::NewGuid().ToString('N')).rollback"
    try {
        [IO.File]::WriteAllBytes($temporaryPath, [byte[]]@())
        Protect-CredentialAcl -Path $temporaryPath
        [IO.File]::WriteAllText($temporaryPath, $updatedText, $utf8)
        $roundTrip = [IO.File]::ReadAllText($temporaryPath, $utf8)
        if ($roundTrip -notmatch '(?m)^BAILIAN_API_KEY=\S.*$') {
            throw "Bailian credential replacement failed strict round-trip verification."
        }
        [IO.File]::Replace($temporaryPath, $resolvedSecret, $rollbackPath, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) { Remove-Item -LiteralPath $temporaryPath -Force }
        if (Test-Path -LiteralPath $rollbackPath) { Remove-Item -LiteralPath $rollbackPath -Force }
    }

    # Purpose: apply the same canonical UTF-8, allow-list, and ACL checks used
    # by every later manual credential replacement.
    & (Join-Path $PSScriptRoot "normalize_local_secret_file.ps1") -SecretFile $SecretFile
    if ($LASTEXITCODE -ne 0) {
        throw "Credential normalization failed after Bailian import."
    }
    Write-Host "Bailian API key imported from CSV without displaying its value."
    Write-Host "Rows scanned: $($rows.Count); selected DashScope-shaped key: 1; workspace header matched ConfigMap."
}
finally {
    # Purpose: release the selected key from this PowerShell process scope.
    Remove-Variable selectedApiKey -ErrorAction SilentlyContinue
}
