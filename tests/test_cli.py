import contextlib
from datetime import date
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "garmin_wrapped_2025_all.py"


def load_report():
    spec = importlib.util.spec_from_file_location("wrapped", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImportTests(unittest.TestCase):
    def test_import_does_not_parse_arguments_install_or_prompt(self):
        # A fresh dependency-free interpreter makes import-time setup observable.
        code = f"""
import builtins, importlib.util, sys
def forbidden(*args, **kwargs):
    raise AssertionError('import must not prompt or install')
builtins.input = forbidden
sys.argv = ['unrelated.py', 'not-a-year']
spec = importlib.util.spec_from_file_location('wrapped', {str(SCRIPT)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.find_steps({{'totalSteps': 123}}) == 123
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-S", "-c", code], cwd=directory,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(result.stdout, "")


class YearTests(unittest.TestCase):
    def setUp(self):
        # Prevent the old import-time prompt from ever reaching a real account.
        try:
            with patch("builtins.input", side_effect=RuntimeError("import prompted")):
                self.report = load_report()
        except Exception as error:
            self.fail(f"Report is not safe to import: {error}")

    def test_default_is_last_completed_year_including_new_year(self):
        for today, expected in [(date(2026, 10, 13), 2025), (date(2027, 1, 1), 2026)]:
            self.assertEqual(self.report.parse_year([], today=today), expected)

    def test_historical_and_current_year_are_accepted(self):
        for argument, expected in [("1900", 1900), ("2024", 2024), ("2026", 2026)]:
            self.assertEqual(self.report.parse_year([argument], today=date(2026, 10, 13)), expected)

    def test_bad_years_and_extra_arguments_fail_before_dependency_or_login(self):
        for args in [["abc"], [""], ["0"], ["1899"], ["10000"], ["2027"], ["2024", "extra"]]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as error:
                with patch.object(self.report, "check_and_install_dependencies",
                                  side_effect=AssertionError("setup reached")):
                    with self.assertRaises(SystemExit) as exited:
                        self.report.cli(args, today=date(2026, 10, 13))
                self.assertEqual(exited.exception.code, 2)
                self.assertIn("error", error.getvalue())

    def test_invalid_script_execution_has_no_dependency_side_effects(self):
        for argument in ["abc", "0", "1899", "9999"]:
            with self.subTest(argument=argument), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, "-S", str(SCRIPT), argument],
                                        cwd=directory, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("year", result.stderr.lower())
                self.assertNotIn("MISSING DEPENDENCIES", result.stdout)
                self.assertEqual(list(Path(directory).iterdir()), [])


class DependencySetupTests(unittest.TestCase):
    def test_incompatible_installed_garmin_is_offered_compatible_requirements(self):
        report = load_report()
        with patch("importlib.metadata.version", return_value="0.3.17"), \
                patch("builtins.input", return_value="n"), \
                patch("subprocess.check_call", side_effect=AssertionError("declined install attempted")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:
                report.check_and_install_dependencies()
        self.assertEqual(exited.exception.code, 1)
        self.assertIn("0.2", output.getvalue())

    def test_missing_dependencies_never_install_into_global_python(self):
        report = load_report()
        original_import = __import__

        def missing_garmin(name, *args, **kwargs):
            if name == "garminconnect":
                raise ImportError("missing in fixture")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=missing_garmin), \
                patch.object(sys, "prefix", sys.base_prefix), \
                patch("builtins.input", side_effect=AssertionError("global install offered")), \
                patch("subprocess.check_call", side_effect=AssertionError("global install attempted")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:
                report.check_and_install_dependencies()
        self.assertEqual(exited.exception.code, 1)
        self.assertIn("venv", output.getvalue())


if __name__ == "__main__":
    unittest.main()
