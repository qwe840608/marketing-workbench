"""Fixed, per-user Windows logon task; never persist a second enabled flag."""

import base64
import os
import subprocess
from pathlib import Path

from fastapi import HTTPException

from app.services import roles
from app.services.posts import _begin_ingest
from app.services.processes import hidden_process_kwargs

TASK_NAME = "MWB-AutoStart"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
IS_WINDOWS = os.name == "nt"

# Only server-owned paths and one internal operation are substituted below.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$root = __ROOT__
$mode = '__MODE__'
$name = 'MWB-AutoStart'
$exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'
$arguments += (Join-Path $root 'scripts\start-all.ps1') + '"'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
function SameUser($value) {
    if ($value -eq $identity.User.Value -or $value -ieq $identity.Name) { return $true }
    # 排程器可能只存短名稱；電腦名稱與帳號同名時短名稱無法直接解析，需補上網域或電腦名稱。
    $names = @($value)
    if (-not $value.Contains('\')) {
        $names += "$env:USERDOMAIN\$value", "$env:COMPUTERNAME\$value"
    }
    foreach ($candidate in $names) {
        try {
            $account = [Security.Principal.NTAccount]::new($candidate)
            $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($sid -eq $identity.User.Value) {
                return $true
            }
        }
        catch { }
    }
    return $false
}
function ReadTask {
    # Enumeration distinguishes absence from failure; same names in other folders conflict.
    return Get-ScheduledTask | Where-Object { $_.TaskName -eq $name }
}
function Matches($task) {
    if (@($task).Count -ne 1 -or $task.TaskPath -ne '\') { return $false }
    $actions = @($task.Actions)
    $triggers = @($task.Triggers)
    if ($actions.Count -ne 1 -or $triggers.Count -ne 1) { return $false }
    $a = $actions[0]; $t = $triggers[0]; $p = $task.Principal; $s = $task.Settings
    return ($a.CimClass.CimClassName -eq 'MSFT_TaskExecAction' -and
        $a.Execute -eq $exe -and $a.Arguments -ceq $arguments -and
        $a.WorkingDirectory -eq $root -and
        $t.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' -and (SameUser $t.UserId) -and
        $t.Enabled -and [Xml.XmlConvert]::ToTimeSpan($t.Delay).TotalSeconds -eq 45 -and
        (SameUser $p.UserId) -and $p.LogonType -eq 'Interactive' -and $p.RunLevel -eq 'Limited' -and
        $s.Enabled -and -not $s.DisallowStartIfOnBatteries -and -not $s.StopIfGoingOnBatteries -and
        $s.MultipleInstances -eq 'IgnoreNew' -and
        [Xml.XmlConvert]::ToTimeSpan($s.ExecutionTimeLimit).TotalMinutes -eq 30)
}
$mutex = [Threading.Mutex]::new($false, 'Local\MWB-AutoStart')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(5000) }
    catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { exit 21 }
    $task = ReadTask
    if ($task -and -not (Matches $task)) { exit 20 }
    if ($mode -eq 'enable' -and -not $task) {
        $principal = New-ScheduledTaskPrincipal -UserId $identity.Name `
            -LogonType Interactive -RunLevel Limited
        $action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
        $trigger.Delay = 'PT45S'
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
        Register-ScheduledTask -TaskName $name -TaskPath '\' -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    } elseif ($mode -eq 'disable' -and $task) {
        Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
    }
    $task = ReadTask
    if ($task -and -not (Matches $task)) { exit 20 }
    if ($task) { exit 10 }
    exit 0
} catch { exit 21 }
finally { if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
"""


def state(enabled=False, *, supported=True, code=None):
    return {"enabled": enabled, "supported": supported, "task_name": TASK_NAME, "code": code}


def execute(mode="read"):
    if not IS_WINDOWS:
        return state(supported=False, code="autostart_unsupported")
    script = SCRIPT.replace("__ROOT__", "'" + str(PROJECT_ROOT).replace("'", "''") + "'")
    script = script.replace("__MODE__", mode)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        executable = (
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-EncodedCommand",
                encoded,
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            **hidden_process_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return state(code="autostart_timeout")
    except (OSError, KeyError):
        return state(code="autostart_failed")
    return state(
        enabled=result.returncode == 10,
        code={0: None, 10: None, 20: "autostart_conflict"}.get(
            result.returncode, "autostart_failed"
        ),
    )


def require_admin(access):
    if not roles.can(access, "settings.manage"):
        raise HTTPException(403, "僅管理員可操作開機自動啟動")


def view(access):
    require_admin(access)
    return execute()


def status(access):
    # Authenticated, read-only workspace information for every role.
    return {"autostart": execute()}


def save(access, body):
    require_admin(access)
    session, actor = access.session, f"staff:{access.staff.id}"
    session.commit()
    result = execute("enable" if body.enabled else "disable")
    if not result["code"] and result["enabled"] != body.enabled:
        result["code"] = "autostart_failed"
    if result["code"] and result["supported"]:
        # A timed-out mutation can have completed; re-read the actual task.
        actual = execute()
        result = {**actual, "code": result["code"]}
    with session.begin():
        audit = _begin_ingest(session, "workspace.autostart")
        audit.actor, audit.target_type = actor, "workspace"
        audit.detail_json = {"enabled": body.enabled, "code": result["code"]}
    return result
