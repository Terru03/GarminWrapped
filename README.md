# Garmin Wrapped Generator

A data visualization tool that generates a "Spotify Wrapped" style report for your Garmin Connect fitness data.

## Features

- **Activity Analysis**: Summarizes total distance, time, and elevation across all activities.
- **Sport Breakdown**: Ranks your top sports by frequency.
- **Wellness Metrics**: Visualizes steps, sleep, stress, body battery, and more.
- **VO2 Max Trends**: Tracks your fitness progress over the year.
- **Badges & PRs**: Highlights achievements and personal records.
- **HTML Report**: Generates a beautiful, shareable HTML dashboard.

## Prerequisites

- [Python 3.13 or 3.14](https://www.python.org/downloads/), standard 64-bit CPython
- A Garmin Connect account

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Terru03/GarminWrapped.git
   cd GarminWrapped
   ```

2. Create a local environment and install dependencies (manual setup):
   ```bash
   python -m venv .venv
   ```
   Windows:
   ```cmd
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
   macOS/Linux:
   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```
   The Windows launcher also creates `.venv` automatically and offers dependency
   installation there. The script never offers installation into global Python.
   Existing environments and token files are preserved; an incomplete or unsupported
   `.venv` must be repaired or renamed before retrying.

   Dependency installation/imports and offline report generation were verified on
   Windows x64 with CPython **3.13.16** and **3.14.8**, using garminconnect **0.2.40**,
   pandas **3.0.6**, tqdm **4.70.1**, and colorama **0.4.6**. Other Python versions and
   free-threaded builds are unverified. Live Garmin authentication/API access was not
   exercised. `garminconnect` remains on 0.2.x to retain the existing login API and
   `.garmin_tokens` format; 0.3 uses a different client/session format.

## Usage

1. Run the batch script (Windows):
   ```cmd
   run_garmin_wrapped.bat
   ```
   Or pass a year: `run_garmin_wrapped.bat 2024`. The launcher searches the local
   environment, `py -3.14`, `py -3.13`, then `python`. For a portable installation,
   set `GARMIN_WRAPPED_PYTHON` to the full `python.exe` path (without surrounding quotes).

2. Or run the Python script directly:
   ```bash
   .venv\Scripts\python garmin_wrapped_2025_all.py [YEAR]
   ```
   On macOS/Linux, use `.venv/bin/python` instead.

   Omit `YEAR` (or press Enter at the Windows prompt) for the **last completed
   calendar year**: 2025 during 2026, 2026 during 2027. Years from **1900 through
   the current year** are accepted. The current year produces a report through
   today. Invalid, out-of-range, future, or extra arguments exit with an error
   before dependency installation or account access. `--help` also works offline.

3. Follow the prompts to log in to your Garmin account.

## Output

The script generates:
- `garmin_wrapped_[YEAR]_report.html`: Interactive dashboard
- `garmin_wrapped_[YEAR]_report.txt`: Text summary
- Monthly, per-sport, activity, and parsed wellness CSVs, plus raw wellness JSON

## Offline tests

```cmd
.venv\Scripts\python -m unittest discover -s tests -v
```

Tests use synthetic activity/wellness responses and temporary output directories;
they do not log in or call Garmin. Importing `garmin_wrapped_2025_all` does not
parse command-line arguments, install packages, prompt, or access an account.

## Security Note

This tool runs locally on your machine. Your Garmin credentials are used only to authenticate with the Garmin Connect API and are stored locally in the `.garmin_tokens` directory. **Never share this directory or your credentials.**
