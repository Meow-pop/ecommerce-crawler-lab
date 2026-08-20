[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot

python -X utf8 -m unittest discover `
    -s (Join-Path $repoRoot 'crawler') `
    -p 'test_*.py' `
    -v
exit $LASTEXITCODE
