[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot
$requirements = Join-Path $repoRoot 'requirements-browser.txt'

python -m pip install --user -r $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Playwright Python 依赖安装失败"
}

Write-Output '浏览器采集依赖已安装。脚本使用电脑现有的 Microsoft Edge，不额外下载浏览器。'
