[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Keyword,

    [ValidateRange(1, 30)]
    [int]$MaxItems = 30
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $repoRoot 'crawler\suning_collector.py'

python -X utf8 $collector `
    $Keyword `
    --max-items $MaxItems `
    --output (Join-Path $repoRoot 'data')
exit $LASTEXITCODE
