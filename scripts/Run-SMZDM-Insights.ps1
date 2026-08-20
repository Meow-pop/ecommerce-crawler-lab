[CmdletBinding()]
param(
    [string]$Category = '保温杯',
    [string]$Url = 'https://www.smzdm.com/fenlei/baowenbaolengbei/',

    [ValidateRange(1, 30)]
    [int]$MaxItems = 30,

    [switch]$Headful
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $repoRoot 'crawler\smzdm_insights.py'

$arguments = @(
    '-X', 'utf8', $collector,
    '--category', $Category,
    '--url', $Url,
    '--max-items', $MaxItems,
    '--output', (Join-Path $repoRoot 'data')
)
if ($Headful) {
    $arguments += '--headful'
}

python @arguments
exit $LASTEXITCODE
