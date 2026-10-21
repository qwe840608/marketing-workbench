import base64
import os
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_classify import classified_data as classified_data

from app.models import AuditLog, Staff
from app.services import autostart


@pytest.fixture
def task(monkeypatch, classified_data):
    calls = []
    state = {"enabled": False, "failure": None}
    monkeypatch.setattr(autostart, "IS_WINDOWS", True)
    monkeypatch.setenv("SystemRoot", "C:\\Windows")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        script = base64.b64decode(args[-1]).decode("utf-16-le")
        if state["failure"] == "timeout":
            raise subprocess.TimeoutExpired(args, 60, output="private-output")
        if state["failure"] == "missing":
            raise OSError("private-output")
        if state["failure"]:
            return SimpleNamespace(returncode=state["failure"])
        if "$mode = 'enable'" in script:
            state["enabled"] = True
        if "$mode = 'disable'" in script:
            state["enabled"] = False
        return SimpleNamespace(returncode=10 if state["enabled"] else 0)

    monkeypatch.setattr(autostart.subprocess, "run", run)
    return state, calls, classified_data["staff_id"]


def test_permissions_and_body(client, task):
    for role in ("marketing", "viewer"):
        with client.app.state.session_factory.begin() as session:
            session.get(Staff, task[2]).role = role
        assert client.get("/api/workspace/autostart").status_code == 403
        assert client.put("/api/workspace/autostart", json={"enabled": True}).status_code == 403
        assert client.get("/api/workspace/status").status_code == 403
    task[1].clear()
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, task[2]).role = "admin"
    for body in (
        {},
        {"enabled": "true"},
        {"enabled": 1},
        {"enabled": None},
        {"enabled": True, "path": "evil"},
        {"enabled": True, "command": "evil"},
        {"enabled": True, "args": []},
    ):
        assert client.put("/api/workspace/autostart", json=body).status_code == 422
    assert not task[1]


def test_fixed_commands_and_actual_state(client, task):
    assert client.get("/api/workspace/autostart").json() == autostart.state()
    for enabled in (True, True, False, False):
        response = client.put("/api/workspace/autostart", json={"enabled": enabled})
        assert response.status_code == 200
        assert response.json() == autostart.state(enabled)
        args, kwargs = task[1][-1]
        assert args[0] == str(
            autostart.Path("C:\\Windows") / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        assert args[1:-1] == [
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-EncodedCommand",
        ]
        assert kwargs["shell"] is False and kwargs["timeout"] == 60
        assert kwargs["stdout"] == kwargs["stderr"] == kwargs["stdin"] == subprocess.DEVNULL
        if os.name == "nt":
            assert kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE
            assert kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
            assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE
        script = base64.b64decode(args[-1]).decode("utf-16-le")
        assert str(autostart.PROJECT_ROOT) in script
        assert autostart.PROJECT_ROOT.is_absolute()
        for token in (
            "scripts\\start-all.ps1",
            "-AtLogOn -User $identity.Name",
            "-LogonType Interactive -RunLevel Limited",
            "-WindowStyle Hidden",
            "-NoProfile -NonInteractive",
            "-ExecutionPolicy Bypass -File",
            "-WorkingDirectory $root",
            "PT45S",
            "-AllowStartIfOnBatteries",
            "-DontStopIfGoingOnBatteries",
            "-MultipleInstances IgnoreNew",
            "New-TimeSpan -Minutes 30",
            "-Confirm:$false",
        ):
            assert token in script
        assert "-Force" not in script
        assert "@($task).Count -ne 1 -or $task.TaskPath -ne '\\'" in script
        assert script.index("if ($task -and -not (Matches $task)) { exit 20 }") < script.index(
            "Register-ScheduledTask"
        )
        assert "$a.Execute -eq $exe" in script and "$a.Arguments -ceq $arguments" in script
        assert "$actions.Count -ne 1 -or $triggers.Count -ne 1" in script
        assert "SameUser $t.UserId" in script and "SameUser $p.UserId" in script
    # GET re-reads externally changed state, without writing audit records.
    task[0]["enabled"] = True
    assert client.get("/api/workspace/autostart").json()["enabled"] is True
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(AuditLog).where(AuditLog.action == "workspace.autostart")
        ).all()
        assert [r.detail_json for r in rows] == [
            {"enabled": v, "code": None} for v in (True, True, False, False)
        ]
        assert all(r.actor == f"staff:{task[2]}" for r in rows)


@pytest.mark.parametrize(
    "failure,code",
    [
        (20, "autostart_conflict"),
        (21, "autostart_failed"),
        (1, "autostart_failed"),
        ("timeout", "autostart_timeout"),
        ("missing", "autostart_failed"),
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_failure_codes_and_safe_audit(client, task, failure, code, enabled):
    task[0]["failure"] = failure
    assert client.get("/api/workspace/autostart").json()["code"] == code
    assert client.put(
        "/api/workspace/autostart", json={"enabled": enabled}
    ).json() == autostart.state(code=code)
    with client.app.state.session_factory() as session:
        row = session.scalar(select(AuditLog).where(AuditLog.action == "workspace.autostart"))
        assert row.detail_json == {"enabled": enabled, "code": code}
        assert row.actor == f"staff:{task[2]}"
        assert "private-output" not in str(row.detail_json)


def test_unsupported(client, task, monkeypatch):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    expected = autostart.state(supported=False, code="autostart_unsupported")
    assert client.get("/api/workspace/autostart").json() == expected
    assert client.put("/api/workspace/autostart", json={"enabled": True}).json() == expected
    assert not task[1]


def test_timeout_refreshes_actual_state(client, task, monkeypatch):
    results = iter([autostart.state(code="autostart_timeout"), autostart.state(True)])
    monkeypatch.setattr(autostart, "execute", lambda *a: next(results))
    assert client.put("/api/workspace/autostart", json={"enabled": True}).json() == autostart.state(
        True, code="autostart_timeout"
    )
