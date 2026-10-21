"""Offline cleanup unit tests and two representative isolated checks."""

import io
import json
import logging
import os
import stat
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from runtime_tmp import (
    RUNTIME,
    cleanup,
    output_dir,
    runtime_check,
    runtime_tmp,
    stop_process,
    temporary_dir,
)


class RuntimeCleanupTests(unittest.TestCase):
    def test_exception_and_interrupt_remove_scratch(self):
        for error in (AssertionError, RuntimeError, KeyboardInterrupt):
            with (
                self.subTest(error=error),
                self.assertRaises(error),
                runtime_tmp("failure") as folder,
            ):
                (folder / "file").write_text("test", encoding="utf-8")
                raise error()
            self.assertFalse(folder.exists())

    def test_readonly_file(self):
        with runtime_tmp("readonly") as folder:
            file = folder / "readonly.txt"
            file.write_text("test", encoding="utf-8")
            file.chmod(stat.S_IREAD)
        self.assertFalse(folder.exists())

    def test_owned_log_handler_is_closed(self):
        logger = logging.getLogger("tmpclean-unit")
        with runtime_tmp("log") as folder:
            handler = logging.FileHandler(folder / "test.log")
            logger.addHandler(handler)
        self.assertNotIn(handler, logger.handlers)
        self.assertIsNone(handler.stream)
        self.assertFalse(folder.exists())

    def test_retry_and_warning_preserve_original_exception(self):
        import runtime_tmp as module

        original = module.shutil.rmtree
        calls = []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError()
            return original(*args, **kwargs)

        with (
            patch.object(module.shutil, "rmtree", side_effect=flaky),
            runtime_tmp("retry") as folder,
        ):
            pass
        self.assertEqual(len(calls), 3)
        self.assertFalse(folder.exists())
        # Nest beneath an owned root so real rmtree eventually removes it.
        with (
            runtime_tmp("warning") as outer,
            patch.object(module, "RUNTIME", outer),
            redirect_stderr(io.StringIO()) as log,
        ):
            with (
                patch.object(module.shutil, "rmtree", side_effect=PermissionError()),
                self.assertRaisesRegex(AssertionError, "original"),
                runtime_tmp("locked"),
            ):
                raise AssertionError("original")
            self.assertIn("WARNING", log.getvalue())

    def test_process_stops_before_removal(self):
        @runtime_check
        def check():
            folder = temporary_dir()
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=folder,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            cleanup(stop_process, process)
            return folder, process

        folder, process = check()
        self.assertIsNotNone(process.poll())
        self.assertFalse(folder.exists())

    def test_latest_output_and_shared_scope(self):
        @runtime_check
        def check():
            directory = output_dir()
            self.assertFalse((directory / "old.txt").exists())
            (directory / "old.txt").write_text("test", encoding="utf-8")
            self.assertEqual(directory, output_dir())

        with patch.object(sys, "argv", ["tmpclean_output_unit.py"]):
            check()
            check()

    def test_representative_checks_leave_no_new_runtime_items(self):
        dist = Path(os.environ["FRONTEND_DIST_DIR"]).resolve()
        self.assertTrue(dist.is_relative_to(RUNTIME.resolve()))
        self.assertTrue((dist / "index.html").is_file())
        before = {p.name for p in RUNTIME.iterdir()}
        # 只看這次新增的項目：長期使用的 checkout 可能留有舊暫存，不是本次檢查的責任。
        tmp = RUNTIME / "tmp"
        tmp_before = {p.name for p in tmp.iterdir()} if tmp.is_dir() else set()
        results = []
        for script in ("check_exports.py", "check_workspace.py"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name(script))],
                cwd=RUNTIME.parent / "backend",
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
                timeout=180,
                check=False,
            )
            log = RUNTIME / "check-output" / "test_runtime_clean"
            log.mkdir(parents=True, exist_ok=True)
            (log / (script + ".log")).write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            after = {p.name for p in RUNTIME.iterdir()}
            self.assertFalse(after - before - {"tmp", "check-output"})
            tmp_after = {p.name for p in tmp.iterdir()} if tmp.is_dir() else set()
            self.assertFalse(tmp_after - tmp_before)
            results.append({"script": script, "exit": result.returncode})
        (log / "result.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    # Do not wrap the suite: the unit cases explicitly exercise separate runs.
    runtime_check(lambda: None)()
    unittest.main()
