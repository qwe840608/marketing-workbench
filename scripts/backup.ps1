param(
    [ValidateSet('run', 'restore')][string]$Action = 'run',
    [string]$Archive,
    [string]$Destination
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '請先執行 start-all.ps1 安裝後端環境。' }
$name = 'Local\MwbBackup-' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($projectRoot)).Replace('/', '_')
$mutex = [Threading.Mutex]::new($false, $name)
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw '已有備份或還原進行中，請等待完成。' }
    $arguments = @((Join-Path $PSScriptRoot 'backup.py'), $Action)
    if ($Archive) { $arguments += @('--archive', $Archive) }
    if ($Destination) { $arguments += @('--destination', $Destination) }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw '備份／還原未完成，請依上方訊息處理後重試。' }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
