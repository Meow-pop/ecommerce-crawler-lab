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
$dataDirectory = Join-Path $repoRoot 'data'
$collector = Join-Path $repoRoot 'crawler\suning_collector.py'
$reporter = Join-Path $repoRoot 'analysis\market_report.py'

python -X utf8 $collector `
    $Keyword `
    --max-items $MaxItems `
    --output $dataDirectory
if ($LASTEXITCODE -ne 0) {
    throw "苏宁采集失败，未生成市场报告"
}

$latest = Get-ChildItem -LiteralPath $dataDirectory -Filter 'suning-*.json' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $latest) {
    throw "找不到采集器生成的 JSON"
}

python -X utf8 $reporter $latest.FullName
exit $LASTEXITCODE
