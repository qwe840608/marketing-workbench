$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'runtime-common.ps1')
$scratch = Join-Path $projectRoot ('.runtime/tmp/launch-test-' + [Guid]::NewGuid().ToString('N'))
try {
[void](New-Item -ItemType Directory -Path (Join-Path $scratch '.runtime') -Force)
Set-Content -LiteralPath (Join-Path $scratch '.runtime/backend.pid') -Value $PID -Encoding ASCII
$refused = $false
try { Stop-MwbProcess -Name backend -Root $scratch } catch { $refused = $true }
if (-not $refused -or -not (Get-Process -Id $PID)) { throw '未正確拒絕不相關程序。' }
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
try {
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $refused = $false
    try { Assert-MwbPortFree -Port $port } catch { $refused = $true }
    if (-not $refused) { throw '未正確拒絕已占用連接埠。' }
} finally { $listener.Stop() }
Assert-MwbPortFree -Port $port
Write-Host '3 passed：不相關 PID 保留、占用連接埠拒絕、釋放後可使用。'

} finally {
    $tmpRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime/tmp'))
    $resolvedScratch = [IO.Path]::GetFullPath($scratch)
    if ([IO.Path]::GetDirectoryName($resolvedScratch) -ne $tmpRoot) { throw 'Invalid scratch path' }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        try {
            if (Test-Path -LiteralPath $resolvedScratch) {
                if ((Get-Item -LiteralPath $resolvedScratch).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Scratch link refused' }
                Remove-Item -LiteralPath $resolvedScratch -Recurse -Force -ErrorAction Stop
            }
            break
        } catch {
            if ($attempt -eq 4) { Write-Warning 'Could not remove launch-test scratch directory' }
            else { Start-Sleep -Milliseconds 150 }
        }
    }
}
