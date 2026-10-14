import contextlib
from datetime import date
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "launch_garmin_wrapped.py"
        self.assertTrue(path.exists(), "Portable launcher is missing")
        spec = importlib.util.spec_from_file_location("launcher", path)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)

    def test_empty_prompt_uses_same_completed_year_before_setup(self):
        with patch("builtins.input", return_value=""), \
                patch.object(self.launcher, "run_report", return_value=7) as run:
            result = self.launcher.main([], today=date(2027, 1, 1))
        self.assertEqual(result, 7)
        run.assert_called_once_with(2026)

    def test_prompted_shell_metacharacters_are_rejected_without_side_effects(self):
        with patch("builtins.input", return_value="2024 & echo injected"), \
                patch.object(self.launcher, "run_report", side_effect=AssertionError("setup reached")), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exited:
                self.launcher.main([], today=date(2026, 10, 13))
        self.assertEqual(exited.exception.code, 2)

    def test_unsupported_python_is_rejected_before_venv_creation(self):
        with patch.object(sys, "version_info", (3, 12, 0)), \
                patch("subprocess.run", side_effect=AssertionError("setup reached")), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(self.launcher.run_report(2024), 1)
        self.assertIn("3.13", error.getvalue())

    def test_windows_batch_invalid_year_preserves_exit_and_creates_no_data(self):
        if os.name != "nt":
            self.skipTest("Windows batch acceptance")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["run_garmin_wrapped.bat", "launch_garmin_wrapped.py", "garmin_wrapped_2025_all.py"]:
                (root / name).write_bytes((ROOT / name).read_bytes())
            env = dict(os.environ, GARMIN_WRAPPED_PYTHON=sys.executable)
            result = subprocess.run(["cmd", "/d", "/c", str(root / "run_garmin_wrapped.bat"), "9999"],
                                    cwd=directory, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("year", result.stderr.lower())
            self.assertFalse((root / ".venv").exists())
            self.assertFalse((root / ".garmin_tokens").exists())
            self.assertEqual(list(root.glob("*_report.*")), [])

    def test_failed_venv_creation_propagates_without_report_success(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(self.launcher, "ROOT", Path(directory)), \
                patch("subprocess.run", return_value=subprocess.CompletedProcess([], 6)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.launcher.run_report(2024), 6)
        self.assertNotIn("Reports:", output.getvalue())

    def test_incomplete_venv_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv").mkdir()
            recovery = root / ".venv" / "recovery"
            recovery.write_text("preserve me")
            with patch.object(self.launcher, "ROOT", root), \
                    patch("subprocess.run", side_effect=AssertionError("existing data overwritten")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.launcher.run_report(2024), 1)
            self.assertEqual(recovery.read_text(), "preserve me")

    def test_real_child_failure_propagates_and_year_is_forwarded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Real venv and subprocess; child replaces account/report boundary only.
            subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True,
                           capture_output=True)
            (root / "garmin_wrapped_2025_all.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "Path('received-year').write_text(sys.argv[1])\nsys.exit(7)\n")
            with patch.object(self.launcher, "ROOT", root), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(self.launcher.run_report(2024), 7)
            self.assertEqual((root / "received-year").read_text(), "2024")
            self.assertNotIn("Reports:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
