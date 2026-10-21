$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'runtime-common.ps1')
Stop-MwbProcess -Name gateway -Root $projectRoot
Stop-MwbProcess -Name backend -Root $projectRoot
Write-Host '本專案的後端與 ngrok 已停止。Tailscale 保留原有內部代理設定。'
