[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Keyword,

    [ValidateRange(1, 10)]
    [int]$Pages = 3,

    [ValidateRange(1, 24)]
    [int]$PageSize = 12,

    [ValidateRange(0, 30)]
    [double]$Delay = 0.5,

    [ValidateRange(0, 5)]
    [int]$MaxRetries = 3
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $repoRoot
try {
    docker compose --profile tools run --rm crawler `
        $Keyword `
        --base-url http://target:8080 `
        --pages $Pages `
        --page-size $PageSize `
        --delay $Delay `
        --max-retries $MaxRetries `
        --output /app/data
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
