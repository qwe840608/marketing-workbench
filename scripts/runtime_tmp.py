"""Owned scratch lifetimes and latest-only acceptance artifacts."""

import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / ".runtime"

try:
    # 完整驗收會平行跑多支檢查，畫面載入較慢；把等待上限放寬到 15 秒，斷言內容不變。
    from playwright.sync_api import expect as _expect

    _expect.set_options(timeout=15_000)
except ImportError:
    pass
_scope = ContextVar("runtime_check_scope", default=None)


def _remove(path, parent):
    path, parent = Path(path), Path(parent).resolve()
    if path.is_symlink() or path.is_junction() or path.resolve().parent != parent:
        raise ValueError("Cleanup requires an owned direct child")

    def writable(function, filename, error):
        os.chmod(filename, os.stat(filename).st_mode | stat.S_IWRITE)
        function(filename)

    for attempt in range(5):
        try:
            if path.exists():
                shutil.rmtree(path, onexc=writable)
            return True
        except OSError:
            time.sleep(0.1 * (attempt + 1))
    print(
        f"WARNING: could not remove acceptance directory: {path.name}", file=sys.stderr
    )
    return False


@contextmanager
def runtime_tmp(prefix="check"):
    """Resources registered on the stack close before scratch is removed."""
    parent = RUNTIME / "tmp"
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink() or parent.is_junction():
        raise ValueError("Scratch root must not be a link")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", prefix)
    folder = Path(tempfile.mkdtemp(prefix=safe + "-", dir=parent))
    try:
        yield folder
    finally:
        # TestClient closes its engine, but the app's file handler outlives its
        # lifespan. Release only handlers belonging to this owned directory.
        loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
        for logger in loggers:
            if not isinstance(logger, logging.Logger):
                continue
            for handler in list(logger.handlers):
                filename = getattr(handler, "baseFilename", None)
                if filename and Path(filename).resolve().is_relative_to(
                    folder.resolve()
                ):
                    logger.removeHandler(handler)
                    handler.close()
        _remove(folder, parent)


def output_path(script=None):
    name = Path(script or sys.argv[0]).stem
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Invalid check name")
    return RUNTIME / "check-output" / name


def output_dir():
    scope = _scope.get()
    if scope is None:
        raise RuntimeError("Use output_dir inside runtime_check")
    if scope["output"] is None:
        path = output_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.parent.is_junction():
            raise ValueError("Output root must not be a link")
        if not _remove(path, path.parent):
            raise RuntimeError("Cannot replace previous check output")
        path.mkdir()
        scope["output"] = path
    return scope["output"]


def temporary_dir():
    return _scope.get()["stack"].enter_context(runtime_tmp(Path(sys.argv[0]).stem))


def cleanup(callback, *args):
    """Register immediately after acquiring an engine, log or child process."""
    _scope.get()["stack"].callback(callback, *args)


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def runtime_check(function):
    @wraps(function)
    def run(*args, **kwargs):
        if _scope.get() is not None:
            return function(*args, **kwargs)
        with ExitStack() as stack:
            token = _scope.set({"stack": stack, "output": None})
            stack.callback(_scope.reset, token)
            output_dir()
            return function(*args, **kwargs)

    return run

def launch_chromium(playwright):
    """Use installed Chrome in either Windows installation scope without user profiles."""
    options = {"channel": "chrome", "headless": True}
    if os.name == "nt":
        bases = [
            os.environ.get(name) for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")
        ]
        system_drive = Path(os.environ.get("SYSTEMDRIVE", "C:") + "/")
        bases.extend([system_drive / "Program Files", system_drive / "Program Files (x86)"])
        for base in bases:
            if not base:
                continue
            executable = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if executable.is_file():
                options["executable_path"] = str(executable)
                break
    return playwright.chromium.launch(**options)
