"""Windows launcher setup; year input stays inside Python, never inside cmd.exe."""
from datetime import date
from pathlib import Path
import subprocess
import sys

from garmin_wrapped_2025_all import SUPPORTED_PYTHON, parse_year


ROOT = Path(__file__).resolve().parent


def run_report(year):
    if sys.version_info[:2] not in SUPPORTED_PYTHON:
        print("Python 3.13 or 3.14 is required; other versions are unverified.", file=sys.stderr)
        return 1

    environment = ROOT / ".venv"
    python = environment / "Scripts" / "python.exe"
    if not python.exists():
        # An existing incomplete environment may contain recovery data. Preserve it.
        if environment.exists():
            print("Existing .venv has no Python executable. Repair it or rename it before retrying.",
                  file=sys.stderr)
            return 1
        result = subprocess.run([sys.executable, "-m", "venv", str(environment)], cwd=ROOT)
        if result.returncode:
            return result.returncode

    # An existing environment may have been created with a different interpreter.
    result = subprocess.run([str(python), "-c",
                             "import sys; sys.exit(0 if sys.version_info[:2] in ((3,13),(3,14)) else 1)"],
                            cwd=ROOT)
    if result.returncode:
        print("Existing .venv needs Python 3.13 or 3.14. Rename it and retry; files were preserved.",
              file=sys.stderr)
        return 1

    result = subprocess.run([str(python), str(ROOT / "garmin_wrapped_2025_all.py"), str(year)], cwd=ROOT)
    if result.returncode == 0:
        print(f"Reports: garmin_wrapped_{year}_report.html and garmin_wrapped_{year}_report.txt")
    return result.returncode


def main(argv=None, *, today=None):
    argv = sys.argv[1:] if argv is None else argv
    today = today or date.today()
    if not argv:
        try:
            answer = input(f"Year (Enter for {today.year - 1}, last completed year): ").strip()
        except EOFError:
            print("No year input received. Pass a year as an argument or run interactively.", file=sys.stderr)
            return 2
        argv = [answer] if answer else []
    year = parse_year(argv, today=today)
    return run_report(year)


if __name__ == "__main__":
    sys.exit(main())
