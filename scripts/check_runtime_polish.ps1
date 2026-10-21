# 完全以程序查詢／停止替身驗證競態，不讀取或停止實機服務。
param([string]$RuntimeFile = (Join-Path $PSScriptRoot 'runtime-common.ps1'))
$ErrorActionPreference = 'Stop'
. $RuntimeFile
$script:stopped = [System.Collections.Generic.List[int]]::new()
$script:scenario = 'missing'
$script:rootProcess = [pscustomobject]@{ ProcessId=101; ParentProcessId=0; CreationDate='same'; Name='node.exe' }
$script:childProcess = [pscustomobject]@{ ProcessId=102; ParentProcessId=101; CreationDate='same'; Name='node.exe' }
function Get-MwbProcess { param($Name,$Root) if ($script:scenario -ne 'root-gone') { return $script:rootProcess } }
function Get-MwbProcessInfo {
    param($Root,[int]$ProcessId=0)
    if (-not $ProcessId) { return @($script:rootProcess,$script:childProcess) }
    if ($ProcessId -eq 101) { return $script:rootProcess }
    if ($script:scenario -eq 'reused') { return [pscustomobject]@{ ProcessId=102; CreationDate='new'; Name='node.exe' } }
    return $script:childProcess
}
function Stop-Process {
    [CmdletBinding()] param([int]$Id)
    if ($Id -eq 102 -and $script:scenario -eq 'missing') {
        $record = [System.Management.Automation.ErrorRecord]::new(
            [ArgumentException]::new('Cannot find a process with the process identifier 102'),
            'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.StopProcessCommand',
            [System.Management.Automation.ErrorCategory]::ObjectNotFound, $Id)
        throw $record
    }
    if ($Id -eq 102 -and $script:scenario -eq 'denied') { throw [UnauthorizedAccessException]::new('Access denied') }
    $script:stopped.Add($Id)
}
Stop-MwbProcess -Name gateway -Root 'isolated-fixture'
if (($script:stopped -join ',') -ne '101') { throw '已消失的子程序應略過，並繼續停止根程序。' }
$script:stopped.Clear(); $script:scenario = 'denied'; $rejected = $false
try { Stop-MwbProcess -Name gateway -Root 'isolated-fixture' } catch [UnauthorizedAccessException] { $rejected = $true }
if (-not $rejected -or $script:stopped.Count) { throw '其他停止錯誤必須中止。' }
$script:scenario = 'reused'
Stop-MwbProcess -Name gateway -Root 'isolated-fixture'
if (($script:stopped -join ',') -ne '101') { throw 'PID 重用不得終止。' }
$script:stopped.Clear(); $script:scenario = 'root-gone'
Stop-MwbProcess -Name gateway -Root 'isolated-fixture'
if ($script:stopped.Count) { throw '根程序已結束應直接完成。' }
Write-Host '4 passed: missing child continues; permission denied aborts; reused PID preserved; missing root succeeds.'
