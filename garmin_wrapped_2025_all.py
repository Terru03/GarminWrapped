from __future__ import annotations

import subprocess
import sys
import argparse
import importlib.metadata

# ─────────────────────────────────────────────────────────────────────────────
# Dependency checker - ensures all required packages are installed
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_PACKAGES = {
    "garminconnect": "garminconnect",
    "pandas": "pandas", 
    "tqdm": "tqdm",
    "colorama": "colorama"
}
SUPPORTED_PYTHON = ((3, 13), (3, 14))

def check_and_install_dependencies():
    """Offer dependency setup; return True when a fresh process is required."""
    missing = []
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(import_name)
            if import_name == "garminconnect":
                installed = importlib.metadata.version(import_name)
                if tuple(installed.split(".")[:2]) != ("0", "2"):
                    print(f"garminconnect {installed} is unsupported; this script requires 0.2.x.")
                    missing.append(pip_name)
        except ImportError:
            missing.append(pip_name)
    
    if missing:
        if sys.prefix == sys.base_prefix:
            print("Missing dependencies. Use run_garmin_wrapped.bat or create a local venv first.")
            sys.exit(1)
        print("\n" + "="*60)
        print("  MISSING OR INCOMPATIBLE DEPENDENCIES")
        print("="*60)
        print(f"\nThe following packages are required but not installed:")
        for pkg in missing:
            print(f"  • {pkg}")
        print(f"\nWould you like to install them now?")
        requirements = Path(__file__).with_name("requirements.txt")
        print(f"  Command: python -m pip install -r \"{requirements}\"")
        
        response = input("\nInstall now? [Y/n]: ").strip().lower()
        if response in ('', 'y', 'yes'):
            print("\nInstalling dependencies...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
                print("\n✓ Dependencies installed successfully!\n")
                return True
            except subprocess.CalledProcessError as e:
                print(f"\n✗ Failed to install dependencies: {e}")
                print("Please install manually: pip install " + " ".join(missing))
                sys.exit(1)
        else:
            print("\nPlease install dependencies manually:")
            print(f"  pip install {' '.join(missing)}")
            print("\nOr use requirements.txt:")
            print("  pip install -r requirements.txt")
            sys.exit(1)
    return False

from datetime import date, timedelta
from pathlib import Path
import json
from typing import Any, Optional
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

def parse_year(argv=None, *, today=None):
    """Validate CLI input before importing dependencies or accessing an account."""
    today = today or date.today()
    parser = argparse.ArgumentParser(description="Generate a Garmin Wrapped report.")
    parser.add_argument("year", nargs="?", type=int, default=today.year - 1,
                        help="1900 through the current year; default: last completed year")
    args = parser.parse_args(argv)
    if not 1900 <= args.year <= today.year:
        parser.error(f"year must be between 1900 and {today.year}; future years are unavailable")
    return args.year


def load_report_dependencies():
    """Load presentation packages only when a report is requested."""
    global pd, tqdm, Fore, Style
    import pandas as pd
    from tqdm import tqdm
    from colorama import init, Fore, Style
    init(autoreset=True)


def cli(argv=None, *, today=None):
    year = parse_year(argv, today=today)
    if sys.version_info[:2] not in SUPPORTED_PYTHON:
        print("Python 3.13 or 3.14 is required; other versions are unverified.", file=sys.stderr)
        return 1
    if check_and_install_dependencies():
        # pip can replace packages already cached in sys.modules. Start clean
        # before importing the client for login, retaining the venv and year.
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), str(year)]).returncode
    main(year, today=today)
    return 0

TOKEN_DIR = Path(".garmin_tokens")

# Text report lines collector
report_lines: list[str] = []

# HTML report data collector
html_data: dict = {
    "year": None,
    "period": "",
    "activities": {},
    "sports": [],
    "wellness": {},
    "steps": {},
}


# -----------------------------
# Helpers
# -----------------------------
def safe_call(obj: Any, method_name: str, *args, **kwargs) -> tuple[bool, Any]:
    fn = getattr(obj, method_name, None)
    if not callable(fn):
        return False, "missing"
    try:
        return True, fn(*args, **kwargs)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def first_ok_call(obj: Any, candidates: list[tuple[str, tuple, dict]]) -> tuple[str, Optional[Any], Optional[str]]:
    last_err = None
    for name, args, kwargs in candidates:
        ok, res = safe_call(obj, name, *args, **kwargs)
        if ok:
            return name, res, None
        if res != "missing":
            last_err = f"{name} -> {res}"
    return "none", None, last_err


def iter_dates(d0: date, d1: date):
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


def normalise_activity_type(val: Any, activity_name: str = "") -> str:
    """Normalize activity type, correcting misclassified 'other' activities based on name."""
    if isinstance(val, dict):
        result = str(val.get("typeKey") or val.get("typeId") or "unknown")
    else:
        result = str(val)
    
    # If type is "other", try to infer from activity name
    if result.lower() == "other" and activity_name:
        name_lower = activity_name.lower()
        # Map keywords in activity name to sport types
        name_to_sport = {
            "soccer": "soccer",
            "football": "soccer",
            "futbol": "soccer",
            "tennis": "tennis_v2",
            "squash": "squash",
            "badminton": "badminton",
            "volleyball": "volleyball",
            "basketball": "basketball",
            "hiking": "hiking",
            "walking": "walking",
            "running": "running",
            "cycling": "cycling",
            "swimming": "lap_swimming",
            "yoga": "yoga",
            "climbing": "indoor_climbing",
            "skiing": "resort_skiing",
            "snowboarding": "resort_snowboarding",
        }
        for keyword, sport in name_to_sport.items():
            if keyword in name_lower:
                return sport
        # Default fallback if no keyword matches
        return "other"
    
    return result


def status_line(msg: str) -> None:
    # true single-line update in terminal
    s = msg[:140]
    sys.stdout.write("\r" + s.ljust(140))
    sys.stdout.flush()


def get_terminal_width() -> int:
    """Get terminal width, default to 80 if unavailable."""
    return shutil.get_terminal_size((80, 20)).columns


def print_header(title: str) -> None:
    """Print a styled section header."""
    width = min(get_terminal_width(), 60)
    print()
    print(f"{Fore.CYAN}{Style.BRIGHT}{'═' * width}")
    print(f"{Fore.CYAN}{Style.BRIGHT}  🏃 {title}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'═' * width}{Style.RESET_ALL}")


def print_subheader(title: str) -> None:
    """Print a styled subsection header."""
    print(f"\n{Fore.YELLOW}{Style.BRIGHT}▸ {title}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{'─' * 40}{Style.RESET_ALL}")


def print_stat(label: str, value: str, icon: str = "•") -> None:
    """Print a single statistic with formatting."""
    print(f"  {Fore.GREEN}{icon}{Style.RESET_ALL} {label}: {Fore.WHITE}{Style.BRIGHT}{value}{Style.RESET_ALL}")


def print_metric_card(name: str, days: int, total_days: int, avg: str, 
                      high_val: str, high_date: str, low_val: str, low_date: str,
                      metric_type: str = "higher_better") -> None:
    """
    Print a wellness metric in a card-like format.
    
    metric_type options:
    - "higher_better": Best=high, Worst=low (e.g., steps, sleep, HRV)
    - "lower_better": Best=low, Worst=high (e.g., resting HR when fit)
    - "neutral": Just show High/Low without judgment (e.g., stress, HR ranges)
    """
    coverage = days / total_days * 100
    coverage_color = Fore.GREEN if coverage > 90 else Fore.YELLOW if coverage > 70 else Fore.RED
    
    print(f"\n  {Fore.CYAN}{Style.BRIGHT}{name}{Style.RESET_ALL}")
    print(f"    ├─ Coverage: {coverage_color}{days}/{total_days} days ({coverage:.0f}%){Style.RESET_ALL}")
    print(f"    ├─ Average:  {Fore.WHITE}{Style.BRIGHT}{avg}{Style.RESET_ALL}")
    
    if metric_type == "higher_better":
        print(f"    ├─ Best:     {Fore.GREEN}🏆 {high_val}{Style.RESET_ALL} ({high_date})")
        print(f"    └─ Worst:    {Fore.RED}📉 {low_val}{Style.RESET_ALL} ({low_date})")
    elif metric_type == "lower_better":
        print(f"    ├─ Best:     {Fore.GREEN}✓ {low_val}{Style.RESET_ALL} ({low_date})")
        print(f"    └─ Worst:    {Fore.RED}⚠ {high_val}{Style.RESET_ALL} ({high_date})")
    else:  # neutral
        print(f"    ├─ High:     {Fore.YELLOW}📈 {high_val}{Style.RESET_ALL} ({high_date})")
        print(f"    └─ Low:      {Fore.BLUE}📉 {low_val}{Style.RESET_ALL} ({low_date})")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"{Fore.GREEN}✓ {msg}{Style.RESET_ALL}")


def print_info(msg: str) -> None:
    """Print an info message."""
    print(f"{Fore.BLUE}ℹ {msg}{Style.RESET_ALL}")


def walk_numbers(obj: Any):
    """Yield all numeric values found recursively in dict/list structures."""
    if isinstance(obj, (int, float)):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_numbers(v)


def find_first_number_by_keys(obj: Any, keys: list[str]) -> Optional[float]:
    """Search dict recursively for first numeric value with a matching key name."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)):
                return float(v)
        for v in obj.values():
            got = find_first_number_by_keys(v, keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_first_number_by_keys(v, keys)
            if got is not None:
                return got
    return None


def find_best_sleep_seconds(obj: Any) -> Optional[int]:
    # Common Garmin sleep totals appear as seconds in one of these keys
    sec = find_first_number_by_keys(obj, ["sleepTimeSeconds", "totalSleepSeconds", "sleepSeconds", "durationSeconds"])
    if sec is not None and sec > 0:
        return int(sec)

    # Sometimes minutes appear
    mins = find_first_number_by_keys(obj, ["sleepTimeMinutes", "totalSleepMinutes", "sleepMinutes", "durationMinutes"])
    if mins is not None and mins > 0:
        return int(mins * 60)

    return None


def find_steps(obj: Any) -> Optional[int]:
    # If it's a list of interval objects (15-min buckets), sum their 'steps' values
    if isinstance(obj, list) and obj:
        # Check if it looks like interval data with 'steps' keys
        if isinstance(obj[0], dict) and "steps" in obj[0]:
            total = sum(item.get("steps", 0) for item in obj if isinstance(item, dict))
            return int(total)  # Return 0 if no steps, still valid data
        # If it's a list of plain numbers, sum them
        if all(isinstance(x, (int, float)) for x in obj):
            return int(sum(obj))
    
    # Try common keys for summary data
    if isinstance(obj, dict):
        v = find_first_number_by_keys(obj, ["totalSteps", "steps", "stepCount", "dailySteps", "value"])
        if v is not None and v >= 0:
            return int(v)
        
        # Check for nested lists
        for k in ["samples", "values", "stepsData", "stepSamples"]:
            s = obj.get(k)
            if isinstance(s, list) and s:
                result = find_steps(s)  # Recursive call
                if result is not None:
                    return result
    
    return None


def find_stress(obj: Any) -> Optional[float]:
    # Averages often show up like this
    v = find_first_number_by_keys(obj, ["avgStressLevel", "averageStressLevel", "stressAvg", "avgStress", "stress"])
    if v is not None and v >= 0:
        return float(v)
    return None


def find_resting_hr(obj: Any) -> Optional[float]:
    v = find_first_number_by_keys(obj, ["restingHeartRate", "rhr", "restingHr", "value"])
    if v is not None and v > 0:
        return float(v)
    return None


def find_hrv(obj: Any) -> Optional[float]:
    v = find_first_number_by_keys(obj, ["hrv", "avgHrv", "hrvAvg", "rmssd", "rmssdAvg", "value"])
    if v is not None and v > 0:
        return float(v)
    return None


def find_body_battery(obj: Any) -> tuple[Optional[float], Optional[float]]:
    # Many shapes: try explicit keys
    high = find_first_number_by_keys(obj, ["bodyBatteryHigh", "high", "max", "maxValue"])
    low = find_first_number_by_keys(obj, ["bodyBatteryLow", "low", "min", "minValue"])
    if high is not None or low is not None:
        return high, low

    # Fallback: if we only have a stream, take max/min of all numbers
    nums = list(walk_numbers(obj))
    nums = [x for x in nums if 0 <= x <= 100]
    if nums:
        return float(max(nums)), float(min(nums))
    return None, None


def find_sleep_score(obj: Any) -> Optional[int]:
    """Extract overall sleep score from sleep data."""
    if not isinstance(obj, dict):
        return None
    
    # Try direct sleepScores path first
    sleep_scores = obj.get("sleepScores") or obj.get("dailySleepDTO", {}).get("sleepScores")
    if isinstance(sleep_scores, dict):
        overall = sleep_scores.get("overall")
        if isinstance(overall, dict) and "value" in overall:
            return int(overall["value"])
        elif isinstance(overall, (int, float)):
            return int(overall)
    
    # Try nested in dailySleepDTO
    daily = obj.get("dailySleepDTO", {})
    if isinstance(daily, dict):
        sleep_scores = daily.get("sleepScores")
        if isinstance(sleep_scores, dict):
            overall = sleep_scores.get("overall")
            if isinstance(overall, dict) and "value" in overall:
                return int(overall["value"])
    
    # Direct key search
    v = find_first_number_by_keys(obj, ["sleepScore", "overallScore", "qualityScore"])
    if v is not None and 0 <= v <= 100:
        return int(v)
    
    return None


def login_garmin() -> Garmin:
    from garminconnect import Garmin
    TOKEN_DIR.mkdir(exist_ok=True)

    api = Garmin("", "")
    try:
        api.login(tokenstore=str(TOKEN_DIR))
        print_success("Logged in using cached tokens")
        return api
    except FileNotFoundError:
        print_info("No cached tokens found - please log in")
        email = input(f"{Fore.CYAN}Garmin email: {Style.RESET_ALL}").strip()
        password = input(f"{Fore.CYAN}Garmin password: {Style.RESET_ALL}").strip()
        api = Garmin(email, password)
        api.login()
        api.garth.dump(str(TOKEN_DIR))
        print_success("Logged in and cached tokens")
        return api
    except Exception:
        print_info("Token refresh needed - please log in")
        email = input(f"{Fore.CYAN}Garmin email: {Style.RESET_ALL}").strip()
        password = input(f"{Fore.CYAN}Garmin password: {Style.RESET_ALL}").strip()
        api = Garmin(email, password)
        api.login()
        api.garth.dump(str(TOKEN_DIR))
        print_success("Logged in (tokens refreshed)")
        return api


def add_report(line: str = ""):
    """Add a line to both console and text report."""
    report_lines.append(line)


def add_report_header(title: str):
    """Add a section header to the report."""
    add_report()
    add_report("=" * 60)
    add_report(f"  {title}")
    add_report("=" * 60)


def add_report_subheader(title: str):
    """Add a subheader to the report."""
    add_report()
    add_report(f">> {title}")
    add_report("-" * 40)


def generate_html_report(filename: str):
    """Generate a styled HTML report."""
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Garmin Wrapped {html_data["year"]}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #fff;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 40px;
            background: rgba(255,255,255,0.1);
            border-radius: 20px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
        }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .header .emoji {{ font-size: 3em; }}
        .header .period {{ color: #888; margin-top: 10px; }}
        .section {{
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
        }}
        .section-title {{
            font-size: 1.4em;
            color: #00d4ff;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}
        .stat-card .value {{ font-size: 1.8em; font-weight: bold; color: #00ff88; }}
        .stat-card .label {{ color: #aaa; font-size: 0.9em; margin-top: 5px; }}
        .sport-item {{
            display: flex;
            align-items: center;
            padding: 12px 15px;
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            margin-bottom: 8px;
        }}
        .sport-rank {{
            font-size: 1.5em;
            width: 50px;
            text-align: center;
        }}
        .sport-name {{ font-weight: bold; flex: 1; }}
        .sport-stats {{ color: #888; font-size: 0.9em; }}
        .metric-card {{
            background: rgba(255,255,255,0.08);
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid #00d4ff;
        }}
        .metric-name {{ font-weight: bold; color: #00d4ff; margin-bottom: 8px; }}
        .metric-row {{ display: flex; justify-content: space-between; padding: 4px 0; color: #ccc; }}
        .metric-row .label {{ color: #888; }}
        .metric-row.best .value {{ color: #00ff88; }}
        .metric-row.worst .value {{ color: #ff6b6b; }}
        .metric-row.high .value {{ color: #ffa500; }}
        .metric-row.low .value {{ color: #87ceeb; }}
        .goals {{ display: flex; gap: 15px; margin-top: 10px; flex-wrap: wrap; }}
        .goal {{ background: rgba(0,255,136,0.2); padding: 8px 15px; border-radius: 20px; font-size: 0.9em; }}
        .footer {{
            text-align: center;
            padding: 30px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="emoji">🏃‍♂️</div>
            <h1>Garmin Wrapped {html_data["year"]}</h1>
            <p>Your Year in Fitness</p>
            <p class="period">{html_data["period"]}</p>
        </div>
'''
    
    # Activities Section
    act = html_data.get("activities", {})
    if act:
        html += '''
        <div class="section">
            <div class="section-title">🏅 Activities</div>
            <div class="stats-grid">
'''
        html += f'''                <div class="stat-card"><div class="value">{act.get("total", 0)}</div><div class="label">Activities</div></div>
                <div class="stat-card"><div class="value">{act.get("distance", "0")} km</div><div class="label">Distance</div></div>
                <div class="stat-card"><div class="value">{act.get("time", "0")} hrs</div><div class="label">Active Time</div></div>
                <div class="stat-card"><div class="value">{act.get("elevation", "0")} m</div><div class="label">Elevation</div></div>
'''
        html += '''            </div>
        </div>
'''
    
    # Sports Section
    sports = html_data.get("sports", [])
    if sports:
        html += '''
        <div class="section">
            <div class="section-title">🎯 Sports Breakdown</div>
'''
        medals = ["🥇", "🥈", "🥉"]
        for i, sport in enumerate(sports):
            rank = medals[i] if i < 3 else f"{i+1}."
            html += f'''            <div class="sport-item">
                <div class="sport-rank">{rank}</div>
                <div class="sport-name">{sport["name"]}</div>
                <div class="sport-stats">{sport["stats"]}</div>
            </div>
'''
        html += '''        </div>
'''
    
    # Wellness Section
    html += '''
        <div class="section">
            <div class="section-title">💚 Wellness Metrics</div>
'''
    
    # Steps
    steps = html_data.get("steps", {})
    if steps.get("total"):
        html += f'''            <div class="metric-card">
                <div class="metric-name">🚶 Steps</div>
                <div class="metric-row"><span class="label">Coverage</span><span>{steps.get("coverage", "N/A")}</span></div>
                <div class="metric-row"><span class="label">Total</span><span class="value">{steps.get("total", "N/A")} steps (~{steps.get("total_km", "0")} km)</span></div>
                <div class="metric-row"><span class="label">Daily Average</span><span>{steps.get("avg", "N/A")} (~{steps.get("avg_km", "0")} km)</span></div>
                <div class="metric-row best"><span class="label">Best Day</span><span class="value">{steps.get("best", "N/A")}</span></div>
                <div class="metric-row worst"><span class="label">Lowest Day</span><span class="value">{steps.get("worst", "N/A")}</span></div>
                <div class="goals">
                    <div class="goal">5k: {steps.get("days_5k", 0)} days</div>
                    <div class="goal">10k: {steps.get("days_10k", 0)} days</div>
                    <div class="goal">15k: {steps.get("days_15k", 0)} days</div>
                </div>
            </div>
'''
    
    # Other wellness metrics
    wellness = html_data.get("wellness", {})
    for name, data in wellness.items():
        if not data.get("avg"):
            continue
        row_class = "high" if data.get("type") == "neutral" else "best"
        low_class = "low" if data.get("type") == "neutral" else "worst"
        high_label = "High" if data.get("type") == "neutral" else "Best"
        low_label = "Low" if data.get("type") == "neutral" else "Worst"
        html += f'''            <div class="metric-card">
                <div class="metric-name">{data.get("icon", "")} {name}</div>
                <div class="metric-row"><span class="label">Coverage</span><span>{data.get("coverage", "N/A")}</span></div>
                <div class="metric-row"><span class="label">Average</span><span>{data.get("avg", "N/A")}</span></div>
                <div class="metric-row {row_class}"><span class="label">{high_label}</span><span class="value">{data.get("high", "N/A")}</span></div>
                <div class="metric-row {low_class}"><span class="label">{low_label}</span><span class="value">{data.get("low", "N/A")}</span></div>
            </div>
'''
    
    html += '''        </div>
'''
    
    # Yearly Totals Section
    totals = html_data.get("totals", {})
    if totals:
        html += '''
        <div class="section">
            <div class="section-title">🔥 Yearly Totals</div>
            <div class="stats-grid">
'''
        html += f'''                <div class="stat-card"><div class="value">{totals.get("calories", "0")}</div><div class="label">Calories Burned</div></div>
                <div class="stat-card"><div class="value">{totals.get("active_calories", "0")}</div><div class="label">Active Calories</div></div>
                <div class="stat-card"><div class="value">{totals.get("floors", "0")}</div><div class="label">Floors Climbed</div></div>
                <div class="stat-card"><div class="value">{totals.get("intensity_minutes", "0")}</div><div class="label">Intensity Minutes</div></div>
'''
        html += '''            </div>
        </div>
'''
    
    # Badges Section
    badges = html_data.get("badges", {})
    if badges.get("count", 0) > 0:
        html += f'''
        <div class="section">
            <div class="section-title">🏅 Badges Earned ({badges.get("count", 0)})</div>
            <div class="stats-grid">
'''
        for badge in badges.get("list", [])[:8]:
            html += f'''                <div class="stat-card" style="padding: 12px;"><div class="value" style="font-size: 1.2em;">🎖️</div><div class="label">{badge.get("name", "")}<br><small>{badge.get("date", "")}</small></div></div>
'''
        html += '''            </div>
        </div>
'''
    
    # Personal Records Section
    prs = html_data.get("personal_records", [])
    if prs:
        html += '''
        <div class="section">
            <div class="section-title">🏆 Personal Records</div>
'''
        for pr in prs:
            star = " ⭐" if pr.get("this_year") else ""
            html += f'''            <div class="metric-card" style="border-left-color: #ffd700;">
                <div class="metric-name">{pr.get("name", "")}{star}</div>
                <div class="metric-row"><span class="label">Record</span><span class="value" style="color: #ffd700;">{pr.get("value", "")}</span></div>
                <div class="metric-row"><span class="label">Set on</span><span>{pr.get("activity", "")} ({pr.get("date", "")})</span></div>
            </div>
'''
        html += '''        </div>
'''
    
    # Fitness Snapshot Section
    race_pred = html_data.get("race_predictions", {})
    vo2 = html_data.get("vo2max", {})
    if race_pred or vo2:
        html += '''
        <div class="section">
            <div class="section-title">🏃 Fitness Snapshot</div>
'''
        # VO2 Max Trend (new detailed version)
        if vo2.get("measurements"):
            trend = vo2.get("trend", "stable")
            trend_color = "#00ff88" if trend == "up" else "#ff6b6b" if trend == "down" else "#ffa500"
            trend_icon = "📈" if trend == "up" else "📉" if trend == "down" else "➡️"
            
            html += f'''            <div class="metric-card" style="border-left-color: {trend_color};">
                <div class="metric-name">❤️ VO2 Max Trend</div>
                <div class="stats-grid" style="margin: 15px 0;">
                    <div class="stat-card"><div class="value">{vo2.get("highest", "N/A")}</div><div class="label">Highest</div></div>
                    <div class="stat-card"><div class="value">{vo2.get("lowest", "N/A")}</div><div class="label">Lowest</div></div>
                    <div class="stat-card"><div class="value" style="color: {trend_color};">{trend_icon} {vo2.get("change", "0")}</div><div class="label">Year Change</div></div>
                </div>
                <div class="metric-row"><span class="label">Start ({vo2.get("start_date", "")})</span><span>{vo2.get("start", "N/A")} ml/kg/min</span></div>
                <div class="metric-row"><span class="label">End ({vo2.get("end_date", "")})</span><span>{vo2.get("end", "N/A")} ml/kg/min</span></div>
'''
            # Add mini chart if we have monthly data
            monthly = vo2.get("monthly", [])
            if monthly:
                # Create an SVG line chart with dots
                max_val = max(m["value"] for m in monthly)
                min_val = min(m["value"] for m in monthly)
                range_val = max(max_val - min_val, 1)
                
                # SVG dimensions
                chart_width = 700
                chart_height = 120
                padding_left = 35
                padding_right = 25
                padding_top = 25
                padding_bottom = 30
                plot_width = chart_width - padding_left - padding_right
                plot_height = chart_height - padding_top - padding_bottom
                
                month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                
                # Calculate points
                points = []
                for i, m in enumerate(monthly):
                    x = padding_left + (i / (len(monthly) - 1)) * plot_width if len(monthly) > 1 else padding_left + plot_width / 2
                    y = padding_top + plot_height - ((m["value"] - min_val) / range_val) * plot_height
                    points.append((x, y, m["value"], m["month"]))
                
                # Create SVG
                html += f'''                <div style="margin-top: 15px; padding: 15px; background: rgba(0,0,0,0.2); border-radius: 8px;">
                    <svg width="100%" viewBox="0 0 {chart_width} {chart_height}" style="max-width: 100%;">
                        <!-- Grid lines -->
                        <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_height}" stroke="#333" stroke-width="1"/>
                        <line x1="{padding_left}" y1="{padding_top + plot_height}" x2="{chart_width - padding_right}" y2="{padding_top + plot_height}" stroke="#333" stroke-width="1"/>
'''
                # Draw horizontal grid lines
                for i in range(3):
                    grid_y = padding_top + (i * plot_height / 2)
                    grid_val = max_val - (i * range_val / 2)
                    html += f'''                        <line x1="{padding_left}" y1="{grid_y}" x2="{chart_width - padding_right}" y2="{grid_y}" stroke="#222" stroke-width="1" stroke-dasharray="4"/>
                        <text x="{padding_left - 5}" y="{grid_y + 4}" fill="#666" font-size="10" text-anchor="end">{grid_val:.0f}</text>
'''
                
                # Draw the gradient fill under the line
                if len(points) > 1:
                    fill_path = f"M {points[0][0]} {padding_top + plot_height} "
                    for x, y, _, _ in points:
                        fill_path += f"L {x} {y} "
                    fill_path += f"L {points[-1][0]} {padding_top + plot_height} Z"
                    html += f'''                        <defs>
                            <linearGradient id="areaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" style="stop-color:#00d4ff;stop-opacity:0.3"/>
                                <stop offset="100%" style="stop-color:#00d4ff;stop-opacity:0.05"/>
                            </linearGradient>
                        </defs>
                        <path d="{fill_path}" fill="url(#areaGradient)"/>
'''
                
                # Draw the connecting line
                if len(points) > 1:
                    line_path = f"M {points[0][0]} {points[0][1]} "
                    for x, y, _, _ in points[1:]:
                        line_path += f"L {x} {y} "
                    html += f'''                        <path d="{line_path}" fill="none" stroke="#00d4ff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
'''
                
                # Draw dots and labels
                for x, y, val, month in points:
                    # Determine dot color
                    if val == max_val:
                        dot_color = "#00ff88"
                        dot_size = 7
                    elif val == min_val:
                        dot_color = "#ff6b6b"
                        dot_size = 7
                    else:
                        dot_color = "#00d4ff"
                        dot_size = 5
                    
                    html += f'''                        <circle cx="{x}" cy="{y}" r="{dot_size}" fill="{dot_color}" stroke="#0a0f1a" stroke-width="2"/>
                        <text x="{x}" y="{y - 10}" fill="#aaa" font-size="10" text-anchor="middle">{val:.0f}</text>
                        <text x="{x}" y="{padding_top + plot_height + 15}" fill="#666" font-size="10" text-anchor="middle">{month_names[month-1]}</text>
'''
                
                html += '''                    </svg>
                </div>
'''
            html += '''            </div>
'''
        elif vo2.get("value"):
            # Fallback to simple display if no trend data
            html += f'''            <div class="stat-card" style="margin-bottom: 20px; background: linear-gradient(135deg, rgba(255,0,100,0.2), rgba(255,100,0,0.2));">
                <div class="value" style="color: #ff6b6b;">VO2 Max: {vo2.get("value")} ml/kg/min</div>
                <div class="label">Last updated: {vo2.get("date", "N/A")}</div>
            </div>
'''
        if race_pred:
            html += '''            <div class="stats-grid">
'''
            for race, time in race_pred.items():
                html += f'''                <div class="stat-card"><div class="value" style="font-size: 1.4em;">{time}</div><div class="label">{race}</div></div>
'''
            html += '''            </div>
'''
        html += '''        </div>
'''
    
    # Weight Section
    weight = html_data.get("weight", {})
    if weight.get("count"):
        change = weight.get("change", "0 kg")
        change_color = "#ff6b6b" if change.startswith("+") else "#00ff88"
        html += f'''
        <div class="section">
            <div class="section-title">⚖️ Weight Tracking</div>
            <div class="stats-grid">
                <div class="stat-card"><div class="value">{weight.get("count", 0)}</div><div class="label">Measurements</div></div>
                <div class="stat-card"><div class="value" style="font-size: 1.2em;">{weight.get("start", "N/A")}</div><div class="label">Start of Year</div></div>
                <div class="stat-card"><div class="value" style="font-size: 1.2em;">{weight.get("end", "N/A")}</div><div class="label">Latest</div></div>
                <div class="stat-card"><div class="value" style="color: {change_color};">{change}</div><div class="label">Change</div></div>
            </div>
        </div>
'''
    
    html += '''
        <div class="footer">
            Generated with ❤️ by Garmin Wrapped
        </div>
    </div>
</body>
</html>'''
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)


# -----------------------------
# Main
# -----------------------------
def main(year=None, *, api=None, today=None):
    """Generate reports; an injected client allows offline fixture generation."""
    today = today or date.today()
    YEAR = parse_year([] if year is None else [str(year)], today=today)
    START_DATE = date(YEAR, 1, 1)
    END_DATE = min(date(YEAR, 12, 31), today)
    load_report_dependencies()
    global report_lines, html_data
    report_lines = []  # Reset for each run
    html_data = {
        "year": YEAR,
        "period": f"{START_DATE} to {END_DATE}",
        "activities": {},
        "sports": [],
        "wellness": {},
        "steps": {},
    }
    
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}"
          f"╔{'═'*50}╗\n"
          f"║{'GARMIN WRAPPED ' + str(YEAR):^50}║\n"
          f"║{'🏃 Your Year in Fitness 🏃':^50}║\n"
          f"╚{'═'*50}╝{Style.RESET_ALL}\n")
    
    # Add header to text report
    add_report("=" * 60)
    add_report(f"           GARMIN WRAPPED {YEAR}")
    add_report(f"           Your Year in Fitness")
    add_report(f"           Period: {START_DATE} to {END_DATE}")
    add_report("=" * 60)

    if api is None:
        api = login_garmin()

    # -------------------------
    # 1) Activities
    # -------------------------
    print_header("ACTIVITIES")
    
    acts: list[dict] = []
    start = 0
    limit = 100

    start_ts = pd.Timestamp(f"{YEAR}-01-01")
    end_ts = pd.Timestamp(END_DATE) + pd.Timedelta(days=1)

    with tqdm(desc="Fetching activities", unit=" batches", 
              bar_format="{l_bar}{bar:30}{r_bar}", colour="cyan") as pbar:
        while True:
            ok, batch = safe_call(api, "get_activities", start, limit)
            if not ok:
                raise RuntimeError(f"get_activities failed: {batch}")
            if not batch:
                break

            acts.extend(batch)
            pbar.update(1)
            pbar.set_postfix(activities=len(acts))

            df_tmp = pd.DataFrame(batch)
            if "startTimeLocal" in df_tmp.columns:
                oldest = pd.to_datetime(df_tmp["startTimeLocal"], errors="coerce").min()
                if pd.notna(oldest) and oldest < start_ts:
                    break

            start += limit

    df = pd.DataFrame(acts)
    df["startTimeLocal"] = pd.to_datetime(df.get("startTimeLocal"), errors="coerce")
    df = df[(df["startTimeLocal"] >= start_ts) & (df["startTimeLocal"] < end_ts)].copy()

    df["month"] = df["startTimeLocal"].dt.to_period("M").astype(str)
    # Missing numeric columns are missing measurements, not scalar values.
    for column in ("distance", "duration", "elevationGain"):
        if column not in df:
            df[column] = pd.Series(index=df.index, dtype=float)
    df["distance_km"] = (pd.to_numeric(df["distance"], errors="coerce").fillna(0) / 1000)
    df["duration_s"] = pd.to_numeric(df["duration"], errors="coerce").fillna(0)
    df["duration_h"] = df["duration_s"] / 3600
    df["elev_m"] = pd.to_numeric(df["elevationGain"], errors="coerce").fillna(0)
    
    # Normalize activity types, using activity name to correct "other" entries
    if df.empty:
        df["activityTypeNorm"] = pd.Series(index=df.index, dtype="string")
    elif "activityType" in df.columns:
        df["activityTypeNorm"] = df.apply(
            lambda row: normalise_activity_type(row["activityType"], row.get("activityName", "")), 
            axis=1
        )
    else:
        df["activityTypeNorm"] = "N/A"
    
    # Filter out non-activity entries (e.g., crash detection)
    excluded_types = ["incident_detected", "incident detected"]
    df = df[~df["activityTypeNorm"].str.lower().isin(excluded_types)]

    top_sport = df["activityTypeNorm"].value_counts().idxmax() if not df.empty else "N/A"

    print_subheader("Activity Summary")
    print_stat("Total Activities", f"{len(df):,}", "🏅")
    print_stat("Total Distance", f"{df['distance_km'].sum():,.1f} km", "📍")
    print_stat("Total Time", f"{df['duration_h'].sum():,.1f} hours", "⏱")
    print_stat("Elevation Gain", f"{df['elev_m'].sum():,.0f} m", "⛰")
    print_stat("Top Sport", top_sport.replace("_", " ").title(), "🥇")
    
    # Add to text report
    add_report_header("ACTIVITIES")
    add_report_subheader("Activity Summary")
    add_report(f"  Total Activities: {len(df):,}")
    add_report(f"  Total Distance:   {df['distance_km'].sum():,.1f} km")
    add_report(f"  Total Time:       {df['duration_h'].sum():,.1f} hours")
    add_report(f"  Elevation Gain:   {df['elev_m'].sum():,.0f} m")
    add_report(f"  Top Sport:        {top_sport.replace('_', ' ').title()}")
    
    # Add to HTML data
    html_data["activities"] = {
        "total": len(df),
        "distance": f"{df['distance_km'].sum():,.1f}",
        "time": f"{df['duration_h'].sum():,.1f}",
        "elevation": f"{df['elev_m'].sum():,.0f}",
        "top_sport": top_sport.replace('_', ' ').title(),
    }

    monthly = df.groupby("month")[["distance_km", "duration_h", "elev_m"]].sum().reset_index()
    monthly.to_csv(f"garmin_wrapped_{YEAR}_monthly.csv", index=False)
    df.to_csv(f"garmin_wrapped_{YEAR}_activities_raw.csv", index=False)

    # -------------------------
    # 1b) By-sport breakdown
    # -------------------------
    df["avg_pace_min_km"] = (df["duration_s"] / 60) / df["distance_km"].replace(0, pd.NA)

    sport_breakdown = (
        df.groupby("activityTypeNorm")
          .agg(
              activities=("activityTypeNorm", "size"),
              total_km=("distance_km", "sum"),
              total_h=("duration_h", "sum"),
              total_elev_m=("elev_m", "sum"),
              avg_km_per_activity=("distance_km", "mean"),
              avg_h_per_activity=("duration_h", "mean"),
              avg_pace_min_km=("avg_pace_min_km", "mean"),
          )
          .reset_index()
          .rename(columns={"activityTypeNorm": "sport"})
          .sort_values("total_h", ascending=False)
    )

    sport_breakdown.to_csv(f"garmin_wrapped_{YEAR}_by_sport.csv", index=False)

    print_subheader(f"All Sports ({len(sport_breakdown)} types)")
    add_report_subheader(f"All Sports ({len(sport_breakdown)} types)")
    medals = ["🥇", "🥈", "🥉"]
    for i, (_, row) in enumerate(sport_breakdown.iterrows(), 1):
        sport_name = str(row['sport']).replace('_', ' ').title()
        if i <= 3:
            prefix = f"  {medals[i-1]}"
        else:
            prefix = f"  {Fore.CYAN}{i:2d}.{Style.RESET_ALL}"
        
        # Format stats - show elevation only if significant
        stats_parts = [f"{row['activities']:.0f} activities"]
        if row['total_km'] > 0.1:
            stats_parts.append(f"{row['total_km']:.1f} km")
        stats_parts.append(f"{row['total_h']:.1f} hrs")
        if row['total_elev_m'] > 100:
            stats_parts.append(f"{row['total_elev_m']:.0f} m ↑")
        
        print(f"{prefix} {Fore.WHITE}{Style.BRIGHT}{sport_name}{Style.RESET_ALL}")
        print(f"      {' • '.join(stats_parts)}")
        
        # Add to text report
        add_report(f"  {i:2d}. {sport_name}: {' | '.join(stats_parts)}")
        
        # Add to HTML data
        html_data["sports"].append({
            "name": sport_name,
            "stats": " • ".join(stats_parts),
        })

    # -------------------------
    # 2) Wellness (daily) - with parallel fetching
    # -------------------------
    print_header("DAILY WELLNESS")
    add_report_header("DAILY WELLNESS")
    
    total_days = (END_DATE - START_DATE).days + 1

    # Fetch daily steps in bulk using get_daily_steps (much more reliable)
    print_info("Fetching daily steps summary...")
    daily_steps_map = {}
    try:
        daily_steps_data = api.get_daily_steps(START_DATE.isoformat(), END_DATE.isoformat())
        if isinstance(daily_steps_data, list):
            for item in daily_steps_data:
                if isinstance(item, dict):
                    cal_date = item.get("calendarDate")
                    steps = item.get("totalSteps", 0)
                    if cal_date:
                        daily_steps_map[cal_date] = steps
        print_success(f"Got steps for {len(daily_steps_map)} days")
    except Exception as e:
        print_info(f"Daily steps bulk fetch failed: {e}")

    method_counts = {
        "steps": {},
        "sleep": {},
        "stress": {},
        "hrv": {},
        "body_battery": {},
        "resting_hr": {},
    }

    def fetch_wellness_for_date(d: date) -> dict:
        """Fetch all wellness data for a single date."""
        ds = d.isoformat()
        
        # Use bulk-fetched steps if available, otherwise fall back to per-day API
        if ds in daily_steps_map:
            steps_m = "get_daily_steps_bulk"
            steps_res = {"totalSteps": daily_steps_map[ds]}
            steps_err = None
        else:
            steps_m, steps_res, steps_err = first_ok_call(api, [
                ("get_steps_data", (ds,), {}),
            ])
        sleep_m, sleep_res, sleep_err = first_ok_call(api, [
            ("get_sleep_data", (ds,), {}),
            ("get_sleep", (ds,), {}),
        ])
        stress_m, stress_res, stress_err = first_ok_call(api, [
            ("get_stress_data", (ds,), {}),
            ("get_stress", (ds,), {}),
        ])
        hrv_m, hrv_res, hrv_err = first_ok_call(api, [
            ("get_hrv_data", (ds,), {}),
            ("get_hrv", (ds,), {}),
        ])
        bb_m, bb_res, bb_err = first_ok_call(api, [
            ("get_body_battery", (ds,), {}),
            ("get_body_battery_data", (ds,), {}),
        ])
        rhr_m, rhr_res, rhr_err = first_ok_call(api, [
            ("get_rhr_day", (ds,), {}),
            ("get_resting_heart_rate", (ds,), {}),
            ("get_rhr", (ds,), {}),
        ])
        
        return {
            "date": ds,
            "steps_method": steps_m, "steps": steps_res,
            "sleep_method": sleep_m, "sleep": sleep_res,
            "stress_method": stress_m, "stress": stress_res,
            "hrv_method": hrv_m, "hrv": hrv_res,
            "body_battery_method": bb_m, "body_battery": bb_res,
            "resting_hr_method": rhr_m, "resting_hr": rhr_res,
            "_errors": "; ".join([e for e in [steps_err, sleep_err, stress_err, hrv_err, bb_err, rhr_err] if e]),
        }

    date_list = list(iter_dates(START_DATE, END_DATE))
    wellness_rows = []
    
    # Use ThreadPoolExecutor for parallel fetching
    MAX_WORKERS = 10
    print_info(f"Fetching with {MAX_WORKERS} parallel connections...")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_date = {executor.submit(fetch_wellness_for_date, d): d for d in date_list}
        
        # Process as they complete with progress bar
        for future in tqdm(as_completed(future_to_date), total=len(date_list),
                          desc="Fetching wellness data", unit=" days",
                          bar_format="{l_bar}{bar:30}{r_bar}", colour="green"):
            result = future.result()
            wellness_rows.append(result)
            
            # Update method counts
            method_counts["steps"][result["steps_method"]] = method_counts["steps"].get(result["steps_method"], 0) + 1
            method_counts["sleep"][result["sleep_method"]] = method_counts["sleep"].get(result["sleep_method"], 0) + 1
            method_counts["stress"][result["stress_method"]] = method_counts["stress"].get(result["stress_method"], 0) + 1
            method_counts["hrv"][result["hrv_method"]] = method_counts["hrv"].get(result["hrv_method"], 0) + 1
            method_counts["body_battery"][result["body_battery_method"]] = method_counts["body_battery"].get(result["body_battery_method"], 0) + 1
            method_counts["resting_hr"][result["resting_hr_method"]] = method_counts["resting_hr"].get(result["resting_hr_method"], 0) + 1
    
    # Sort by date since parallel execution returns out of order
    wellness_rows.sort(key=lambda x: x["date"])

    with open(f"garmin_wrapped_{YEAR}_wellness_raw.json", "w", encoding="utf-8") as f:
        json.dump(wellness_rows, f, ensure_ascii=False, indent=2)

    # -------------------------
    # 2b) Parse wellness summary
    # -------------------------
    parsed = []
    for r in wellness_rows:
        steps = find_steps(r.get("steps"))
        sleep_sec = find_best_sleep_seconds(r.get("sleep"))
        sleep_score = find_sleep_score(r.get("sleep"))
        stress = find_stress(r.get("stress"))
        rhr = find_resting_hr(r.get("resting_hr"))
        hrv = find_hrv(r.get("hrv"))
        bb_high, bb_low = find_body_battery(r.get("body_battery"))

        parsed.append({
            "date": r["date"],
            "steps": steps,
            "sleep_hours": (sleep_sec / 3600) if sleep_sec else None,
            "sleep_score": sleep_score,
            "stress": stress,
            "resting_hr": rhr,
            "hrv": hrv,
            "body_battery_high": bb_high,
            "body_battery_low": bb_low,
        })

    pdf = pd.DataFrame(parsed)
    pdf.to_csv(f"garmin_wrapped_{YEAR}_wellness_parsed.csv", index=False)

    def summarise_metric(name: str, s: pd.Series, fmt: str, unit: str = "", metric_type: str = "higher_better"):
        """
        Display a wellness metric summary.
        
        metric_type options:
        - "higher_better": Best=high, Worst=low (e.g., steps, sleep, HRV)
        - "lower_better": Best=low, Worst=high (e.g., resting HR for athletes)
        - "neutral": Just show High/Low without judgment (e.g., stress, HR ranges)
        """
        s2 = s.dropna()
        if s2.empty:
            print(f"\n  {Fore.CYAN}{Style.BRIGHT}{name}{Style.RESET_ALL}")
            print(f"    {Fore.RED}No data available{Style.RESET_ALL}")
            add_report(f"\n  {name}: No data available")
            return
        high_idx = s2.idxmax()
        low_idx = s2.idxmin()
        unit_str = f" {unit}" if unit else ""
        
        # Add to text report
        avg_val = f"{format(s2.mean(), fmt)}{unit_str}"
        high_val = f"{format(s2.loc[high_idx], fmt)}{unit_str}"
        low_val = f"{format(s2.loc[low_idx], fmt)}{unit_str}"
        high_date = pdf.loc[high_idx, 'date']
        low_date = pdf.loc[low_idx, 'date']
        
        add_report(f"\n  {name}")
        add_report(f"    Coverage: {len(s2)}/{total_days} days ({len(s2)/total_days*100:.0f}%)")
        add_report(f"    Average:  {avg_val}")
        if metric_type == "neutral":
            add_report(f"    High:     {high_val} ({high_date})")
            add_report(f"    Low:      {low_val} ({low_date})")
        else:
            add_report(f"    Best:     {high_val} ({high_date})")
            add_report(f"    Worst:    {low_val} ({low_date})")
        
        # Add to HTML data
        icon_map = {
            "Sleep Duration": "😴",
            "Sleep Score": "💤",
            "Stress": "🧠",
            "Resting HR": "❤️",
            "HRV": "📊",
            "Body Battery High": "🔋",
        }
        html_data["wellness"][name] = {
            "icon": icon_map.get(name, "📈"),
            "coverage": f"{len(s2)}/{total_days} days ({len(s2)/total_days*100:.0f}%)",
            "avg": avg_val,
            "high": f"{high_val} ({high_date})",
            "low": f"{low_val} ({low_date})",
            "type": metric_type,
        }
        
        print_metric_card(
            name=name,
            days=len(s2),
            total_days=total_days,
            avg=avg_val,
            high_val=high_val,
            high_date=high_date,
            low_val=low_val,
            low_date=low_date,
            metric_type=metric_type
        )

    def summarise_steps(steps_series: pd.Series, dates_series: pd.Series):
        """Display detailed steps statistics."""
        # Filter to only days with actual step data (> 0)
        valid_mask = steps_series.notna() & (steps_series > 0)
        s = steps_series[valid_mask]
        dates = dates_series[valid_mask]
        
        if s.empty:
            print(f"\n  {Fore.CYAN}{Style.BRIGHT}Steps{Style.RESET_ALL}")
            print(f"    {Fore.RED}No valid step data available{Style.RESET_ALL}")
            return
        
        # Basic stats
        total_steps = int(s.sum())
        avg_steps = int(s.mean())
        median_steps = int(s.median())
        days_tracked = len(s)
        
        # Best/worst days
        best_idx = s.idxmax()
        worst_idx = s.idxmin()
        best_steps = int(s.loc[best_idx])
        worst_steps = int(s.loc[worst_idx])
        best_date = dates.loc[best_idx]
        worst_date = dates.loc[worst_idx]
        
        # Goal achievement (common goals)
        days_over_5k = int((s >= 5000).sum())
        days_over_10k = int((s >= 10000).sum())
        days_over_15k = int((s >= 15000).sum())
        
        # Distance estimate (personal stride length ~0.81m based on user data)
        STRIDE_LENGTH_M = 0.81
        total_km = (total_steps * STRIDE_LENGTH_M) / 1000
        avg_km = (avg_steps * STRIDE_LENGTH_M) / 1000
        
        # Coverage percentage
        coverage = days_tracked / total_days * 100
        coverage_color = Fore.GREEN if coverage > 90 else Fore.YELLOW if coverage > 70 else Fore.RED
        
        print(f"\n  {Fore.CYAN}{Style.BRIGHT}Steps{Style.RESET_ALL}")
        print(f"    Coverage: {coverage_color}{days_tracked}/{total_days} days ({coverage:.0f}%){Style.RESET_ALL}")
        print(f"    Total:    {Fore.WHITE}{Style.BRIGHT}{total_steps:,} steps{Style.RESET_ALL} (~{total_km:,.1f} km)")
        print(f"    Average:  {Fore.WHITE}{Style.BRIGHT}{avg_steps:,}/day{Style.RESET_ALL} (~{avg_km:.1f} km/day)")
        print(f"    Best:     {Fore.GREEN}{best_steps:,}{Style.RESET_ALL} ({best_date})")
        print(f"    Lowest:   {Fore.YELLOW}{worst_steps:,}{Style.RESET_ALL} ({worst_date})")
        goals_line = f"{Fore.GREEN}5k: {days_over_5k} days{Style.RESET_ALL} | "
        goals_line += f"{Fore.CYAN}10k: {days_over_10k} days{Style.RESET_ALL} | "
        goals_line += f"{Fore.MAGENTA}15k: {days_over_15k} days{Style.RESET_ALL}"
        print(f"    Goals:    {goals_line}")
        
        # Add to text report
        add_report(f"\n  Steps")
        add_report(f"    Coverage: {days_tracked}/{total_days} days ({coverage:.0f}%)")
        add_report(f"    Total:    {total_steps:,} steps (~{total_km:,.1f} km)")
        add_report(f"    Average:  {avg_steps:,}/day (~{avg_km:.1f} km/day)")
        add_report(f"    Best:     {best_steps:,} ({best_date})")
        add_report(f"    Lowest:   {worst_steps:,} ({worst_date})")
        add_report(f"    Goals:    5k: {days_over_5k} days | 10k: {days_over_10k} days | 15k: {days_over_15k} days")
        
        # Add to HTML data
        html_data["steps"] = {
            "coverage": f"{days_tracked}/{total_days} days ({coverage:.0f}%)",
            "total": f"{total_steps:,}",
            "total_km": f"{total_km:,.1f}",
            "avg": f"{avg_steps:,}/day",
            "avg_km": f"{avg_km:.1f}",
            "best": f"{best_steps:,} ({best_date})",
            "worst": f"{worst_steps:,} ({worst_date})",
            "days_5k": days_over_5k,
            "days_10k": days_over_10k,
            "days_15k": days_over_15k,
        }

    print_subheader("Wellness Metrics")
    add_report_subheader("Wellness Metrics")
    summarise_steps(pdf["steps"], pdf["date"])
    summarise_metric("Sleep Duration", pdf["sleep_hours"], ".2f", unit="hrs", metric_type="higher_better")
    summarise_metric("Sleep Score", pdf["sleep_score"], ".0f", unit="/100", metric_type="higher_better")
    summarise_metric("Stress", pdf["stress"], ".1f", metric_type="neutral")
    summarise_metric("Resting HR", pdf["resting_hr"], ".1f", unit="bpm", metric_type="neutral")
    summarise_metric("HRV", pdf["hrv"], ".1f", unit="ms", metric_type="higher_better")
    summarise_metric("Body Battery High", pdf["body_battery_high"], ".0f", metric_type="higher_better")

    # -------------------------
    # 3) Calories & Floors from wellness data
    # -------------------------
    print_header("YEARLY TOTALS")
    add_report_header("YEARLY TOTALS")
    
    # Calculate totals from daily data (we'll fetch user_summary for full year)
    total_calories = 0
    total_active_calories = 0
    total_floors = 0
    total_intensity_minutes = 0
    
    print_info("Fetching daily summaries for calories/floors...")
    
    def fetch_daily_summary(d: date) -> dict:
        ds = d.isoformat()
        try:
            summary = api.get_user_summary(ds)
            return {
                "date": ds,
                "total_calories": summary.get("totalKilocalories") or 0,
                "active_calories": summary.get("activeKilocalories") or 0,
                "floors": summary.get("floorsAscended") or 0,
                "intensity_moderate": summary.get("moderateIntensityMinutes") or 0,
                "intensity_vigorous": summary.get("vigorousIntensityMinutes") or 0,
            }
        except Exception:
            return {"date": ds, "total_calories": 0, "active_calories": 0, "floors": 0, 
                    "intensity_moderate": 0, "intensity_vigorous": 0}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_daily_summary, d): d for d in date_list}
        daily_summaries = []
        for future in tqdm(as_completed(futures), total=len(date_list),
                          desc="Fetching daily summaries", unit=" days",
                          bar_format="{l_bar}{bar:30}{r_bar}", colour="cyan"):
            daily_summaries.append(future.result())
    
    for ds in daily_summaries:
        total_calories += ds["total_calories"]
        total_active_calories += ds["active_calories"]
        total_floors += ds["floors"]
        total_intensity_minutes += ds["intensity_moderate"] + (ds["intensity_vigorous"] * 2)
    
    # Floors to elevation (1 floor ≈ 3m)
    total_floors_meters = total_floors * 3
    
    print_subheader("Calories & Activity")
    print_stat("Total Calories Burned", f"{total_calories:,.0f} kcal", "🔥")
    print_stat("Active Calories", f"{total_active_calories:,.0f} kcal", "💪")
    print_stat("Floors Climbed", f"{total_floors:,.0f} floors (~{total_floors_meters:,.0f} m)", "🏢")
    print_stat("Intensity Minutes", f"{total_intensity_minutes:,.0f} min", "⏱️")
    
    add_report_subheader("Calories & Activity")
    add_report(f"  Total Calories Burned: {total_calories:,.0f} kcal")
    add_report(f"  Active Calories:       {total_active_calories:,.0f} kcal")
    add_report(f"  Floors Climbed:        {total_floors:,.0f} floors (~{total_floors_meters:,.0f} m)")
    add_report(f"  Intensity Minutes:     {total_intensity_minutes:,.0f} min")
    
    html_data["totals"] = {
        "calories": f"{total_calories:,.0f}",
        "active_calories": f"{total_active_calories:,.0f}",
        "floors": f"{total_floors:,.0f}",
        "floors_meters": f"{total_floors_meters:,.0f}",
        "intensity_minutes": f"{total_intensity_minutes:,.0f}",
    }

    # -------------------------
    # 4) Badges Earned This Year
    # -------------------------
    print_header("ACHIEVEMENTS")
    add_report_header("ACHIEVEMENTS")
    
    try:
        all_badges = api.get_earned_badges()
        year_badges = [b for b in all_badges if str(YEAR) in str(b.get("badgeEarnedDate", ""))]
        
        print_subheader(f"Badges Earned in {YEAR}")
        print_stat("Total Badges Earned", f"{len(year_badges)}", "🏅")
        
        add_report_subheader(f"Badges Earned in {YEAR}")
        add_report(f"  Total: {len(year_badges)} badges")
        
        html_data["badges"] = {
            "count": len(year_badges),
            "list": [],
        }
        
        if year_badges:
            print(f"\n  {Fore.CYAN}Recent badges:{Style.RESET_ALL}")
            for b in sorted(year_badges, key=lambda x: x.get("badgeEarnedDate", ""), reverse=True)[:8]:
                name = b.get("badgeName", "Unknown")
                earned_date = str(b.get("badgeEarnedDate", ""))[:10]
                print(f"    {Fore.YELLOW}🎖️{Style.RESET_ALL} {name} ({earned_date})")
                add_report(f"    {name} ({earned_date})")
                html_data["badges"]["list"].append({"name": name, "date": earned_date})
            
            if len(year_badges) > 8:
                print(f"    {Fore.BLUE}...and {len(year_badges) - 8} more{Style.RESET_ALL}")
                add_report(f"    ...and {len(year_badges) - 8} more")
    except Exception as e:
        print(f"  {Fore.RED}Could not fetch badges: {e}{Style.RESET_ALL}")
        html_data["badges"] = {"count": 0, "list": []}

    # -------------------------
    # 5) Personal Records
    # -------------------------
    try:
        all_prs = api.get_personal_record()
        
        # PR type mappings (from Garmin API)
        pr_types = {
            1: ("Fastest 1 km", "running", lambda v: f"{v/60:.2f} min"),
            3: ("Fastest 1 Mile", "running", lambda v: f"{v/60:.2f} min"),
            4: ("Fastest 5K", "running", lambda v: f"{v/60:.1f} min"),
            7: ("Fastest 10K", "running", lambda v: f"{v/60:.1f} min"),
            8: ("Longest Cycling", "cycling", lambda v: f"{v/1000:.1f} km"),
            9: ("Max Elevation Gain", "cycling", lambda v: f"{v:.0f} m"),
            12: ("Most Steps (Day)", "steps", lambda v: f"{v:,.0f}"),
            13: ("Most Steps (Week)", "steps", lambda v: f"{v:,.0f}"),
            14: ("Most Steps (Month)", "steps", lambda v: f"{v:,.0f}"),
        }
        
        print_subheader("Personal Records (All Time)")
        add_report_subheader("Personal Records (All Time)")
        
        html_data["personal_records"] = []
        
        for pr in all_prs:
            type_id = pr.get("typeId")
            if type_id in pr_types:
                name, category, formatter = pr_types[type_id]
                value = pr.get("value", 0)
                activity = pr.get("activityName", "")
                pr_date = str(pr.get("actStartDateTimeInGMTFormatted", ""))[:10]
                
                formatted_val = formatter(value)
                
                # Check if set in current year
                year_marker = f" {Fore.GREEN}⭐ {YEAR}{Style.RESET_ALL}" if str(YEAR) in pr_date else ""
                
                print(f"    {Fore.YELLOW}🏆{Style.RESET_ALL} {name}: {Fore.WHITE}{Style.BRIGHT}{formatted_val}{Style.RESET_ALL}")
                if activity and pr_date:
                    print(f"       {Fore.BLUE}{activity} ({pr_date}){year_marker}{Style.RESET_ALL}")
                
                add_report(f"    {name}: {formatted_val}")
                if activity:
                    add_report(f"       {activity} ({pr_date})")
                
                html_data["personal_records"].append({
                    "name": name,
                    "value": formatted_val,
                    "activity": activity,
                    "date": pr_date,
                    "this_year": str(YEAR) in pr_date,
                })
    except Exception as e:
        print(f"  {Fore.RED}Could not fetch personal records: {e}{Style.RESET_ALL}")
        html_data["personal_records"] = []

    # -------------------------
    # 6) Fitness Snapshot (VO2Max for year end, Race Predictions only for current year)
    # -------------------------
    print_header("FITNESS SNAPSHOT")
    add_report_header("FITNESS SNAPSHOT")
    
    # Race predictions - only show for current year since API returns current predictions
    is_current_year = YEAR == date.today().year
    
    if is_current_year:
        try:
            # Race predictions
            race_pred = api.get_race_predictions()
            if race_pred:
                print_subheader("Race Time Predictions (Current)")
                add_report_subheader("Race Time Predictions (Current)")
                
                html_data["race_predictions"] = {}
                
                def format_race_time(seconds):
                    if not seconds:
                        return "N/A"
                    hours = int(seconds // 3600)
                    minutes = int((seconds % 3600) // 60)
                    secs = int(seconds % 60)
                    if hours > 0:
                        return f"{hours}:{minutes:02d}:{secs:02d}"
                    return f"{minutes}:{secs:02d}"
                
                times = [
                    ("5K", race_pred.get("time5K")),
                    ("10K", race_pred.get("time10K")),
                    ("Half Marathon", race_pred.get("timeHalfMarathon")),
                    ("Marathon", race_pred.get("timeMarathon")),
                ]
                
                for name, seconds in times:
                    if seconds:
                        formatted = format_race_time(seconds)
                        print_stat(name, formatted, "🏃")
                        add_report(f"  {name}: {formatted}")
                        html_data["race_predictions"][name] = formatted
        except Exception as e:
            print(f"  {Fore.YELLOW}Race predictions not available{Style.RESET_ALL}")
            html_data["race_predictions"] = {}
    else:
        html_data["race_predictions"] = {}
    
    # VO2 Max Trend Analysis - fetch monthly snapshots
    print_subheader("VO2 Max Trend")
    add_report_subheader("VO2 Max Trend")
    
    vo2_monthly = []
    try:
        # Sample VO2 Max at the end of each month
        for month in range(1, 13):
            # Skip future months for current year
            month_end = date(YEAR, month, 28)  # Use 28 to avoid month-end issues
            if month_end > END_DATE:
                break
            
            try:
                ts = api.get_training_status(month_end.isoformat())
                if ts and "mostRecentVO2Max" in ts:
                    vo2_data = ts["mostRecentVO2Max"].get("generic", {})
                    vo2_val = vo2_data.get("vo2MaxValue")
                    vo2_date = vo2_data.get("calendarDate", "")
                    if vo2_val and vo2_date and vo2_date.startswith(str(YEAR)):
                        vo2_monthly.append({
                            "month": month,
                            "value": vo2_val,
                            "date": vo2_date,
                        })
            except Exception:
                pass
        
        if vo2_monthly:
            # Get unique measurements (by date) to avoid duplicates
            seen_dates = set()
            unique_vo2 = []
            for v in vo2_monthly:
                if v["date"] not in seen_dates:
                    seen_dates.add(v["date"])
                    unique_vo2.append(v)
            
            values = [v["value"] for v in unique_vo2]
            highest = max(values)
            lowest = min(values)
            first_val = unique_vo2[0]["value"]
            last_val = unique_vo2[-1]["value"]
            change = last_val - first_val
            
            # Determine trend
            if change > 0:
                trend_icon = "📈"
                trend_text = f"+{change:.0f}"
                trend_color = Fore.GREEN
            elif change < 0:
                trend_icon = "📉"
                trend_text = f"{change:.0f}"
                trend_color = Fore.RED
            else:
                trend_icon = "➡️"
                trend_text = "0"
                trend_color = Fore.YELLOW
            
            print_stat("Measurements", f"{len(unique_vo2)} readings", "📊")
            print_stat("Highest", f"{highest:.0f} ml/kg/min", "🔝")
            print_stat("Lowest", f"{lowest:.0f} ml/kg/min", "🔻")
            print(f"    {Fore.BLUE}Start of Year:{Style.RESET_ALL} {first_val:.0f} ({unique_vo2[0]['date']})")
            print(f"    {Fore.BLUE}End of Year:{Style.RESET_ALL}   {last_val:.0f} ({unique_vo2[-1]['date']})")
            print(f"    {Fore.BLUE}Year Change:{Style.RESET_ALL}   {trend_color}{trend_icon} {trend_text} ml/kg/min{Style.RESET_ALL}")
            
            # ASCII trend line
            month_names = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
            trend_line = "    Trend: "
            last_printed_val = None
            for m in range(1, 13):
                month_data = next((v for v in vo2_monthly if v["month"] == m), None)
                if month_data:
                    val = month_data["value"]
                    if last_printed_val is None:
                        trend_line += f"{Fore.CYAN}{val:.0f}{Style.RESET_ALL}"
                    elif val > last_printed_val:
                        trend_line += f"{Fore.GREEN}↗{val:.0f}{Style.RESET_ALL}"
                    elif val < last_printed_val:
                        trend_line += f"{Fore.RED}↘{val:.0f}{Style.RESET_ALL}"
                    else:
                        trend_line += f"{Fore.YELLOW}→{val:.0f}{Style.RESET_ALL}"
                    last_printed_val = val
                elif m <= END_DATE.month:
                    trend_line += "·"
            print(trend_line)
            print(f"           {Fore.BLUE}{''.join(month_names[:min(END_DATE.month, 12)])}{Style.RESET_ALL}")
            
            add_report(f"  Measurements: {len(unique_vo2)} readings")
            add_report(f"  Highest:      {highest:.0f} ml/kg/min")
            add_report(f"  Lowest:       {lowest:.0f} ml/kg/min")
            add_report(f"  Start:        {first_val:.0f} ({unique_vo2[0]['date']})")
            add_report(f"  End:          {last_val:.0f} ({unique_vo2[-1]['date']})")
            add_report(f"  Year Change:  {trend_text} ml/kg/min")
            
            html_data["vo2max"] = {
                "measurements": len(unique_vo2),
                "highest": f"{highest:.0f}",
                "lowest": f"{lowest:.0f}",
                "start": f"{first_val:.0f}",
                "start_date": unique_vo2[0]["date"],
                "end": f"{last_val:.0f}",
                "end_date": unique_vo2[-1]["date"],
                "change": f"{trend_text}",
                "trend": "up" if change > 0 else "down" if change < 0 else "stable",
                "monthly": [{"month": v["month"], "value": v["value"], "date": v["date"]} for v in vo2_monthly],
            }
        else:
            print(f"  {Fore.YELLOW}No VO2 Max data available for {YEAR}{Style.RESET_ALL}")
            add_report(f"  No VO2 Max data available for {YEAR}")
            html_data["vo2max"] = {}
    except Exception as e:
        print(f"  {Fore.YELLOW}VO2 Max trend not available{Style.RESET_ALL}")
        html_data["vo2max"] = {}

    # -------------------------
    # 7) Weight Tracking
    # -------------------------
    try:
        body_comp = api.get_body_composition(START_DATE.isoformat(), END_DATE.isoformat())
        weights = body_comp.get("dateWeightList", [])
        
        if weights:
            print_subheader("Weight Tracking")
            add_report_subheader("Weight Tracking")
            
            # Convert to kg (stored in grams)
            weight_data = [(w.get("calendarDate"), w.get("weight", 0) / 1000) for w in weights if w.get("weight")]
            weight_data.sort(key=lambda x: x[0])
            
            if len(weight_data) >= 2:
                first_date, first_weight = weight_data[0]
                last_date, last_weight = weight_data[-1]
                change = last_weight - first_weight
                change_str = f"+{change:.1f}" if change > 0 else f"{change:.1f}"
                change_color = Fore.RED if change > 0 else Fore.GREEN
                
                print_stat("Measurements", f"{len(weight_data)} entries", "⚖️")
                print(f"    {Fore.BLUE}Start ({first_date}):{Style.RESET_ALL} {first_weight:.1f} kg")
                print(f"    {Fore.BLUE}Latest ({last_date}):{Style.RESET_ALL} {last_weight:.1f} kg")
                print(f"    {Fore.BLUE}Change:{Style.RESET_ALL} {change_color}{change_str} kg{Style.RESET_ALL}")
                
                add_report(f"  Measurements: {len(weight_data)} entries")
                add_report(f"  Start ({first_date}): {first_weight:.1f} kg")
                add_report(f"  Latest ({last_date}): {last_weight:.1f} kg")
                add_report(f"  Change: {change_str} kg")
                
                html_data["weight"] = {
                    "count": len(weight_data),
                    "start": f"{first_weight:.1f} kg ({first_date})",
                    "end": f"{last_weight:.1f} kg ({last_date})",
                    "change": f"{change_str} kg",
                }
    except Exception as e:
        print(f"  {Fore.YELLOW}Weight data not available{Style.RESET_ALL}")
        html_data["weight"] = {}

    # -------------------------
    # Final Summary
    # -------------------------
    
    # Save text report
    report_filename = f"garmin_wrapped_{YEAR}_report.txt"
    add_report()
    add_report("=" * 60)
    add_report(f"  Report generated: {date.today().isoformat()}")
    add_report("=" * 60)
    
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    
    # Save HTML report
    html_filename = f"garmin_wrapped_{YEAR}_report.html"
    generate_html_report(html_filename)
    
    print_header("FILES SAVED")
    files = [
        (f"garmin_wrapped_{YEAR}_monthly.csv", "Monthly aggregates"),
        (f"garmin_wrapped_{YEAR}_by_sport.csv", "Per-sport breakdown"),
        (f"garmin_wrapped_{YEAR}_activities_raw.csv", "Raw activity data"),
        (f"garmin_wrapped_{YEAR}_wellness_raw.json", "Raw wellness responses"),
        (f"garmin_wrapped_{YEAR}_wellness_parsed.csv", "Parsed wellness metrics"),
        (report_filename, "Summary report (text)"),
        (html_filename, "Styled report (HTML) ✨"),
    ]
    for filename, description in files:
        print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {Fore.WHITE}{filename}{Style.RESET_ALL}")
        print(f"    {Fore.BLUE}{description}{Style.RESET_ALL}")
    
    print(f"\n  {Fore.CYAN}🔐 Tokens cached in:{Style.RESET_ALL} {TOKEN_DIR.resolve()}")
    
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}"
          f"╔{'═'*50}╗\n"
          f"║{'🎉 Your Garmin Wrapped is complete! 🎉':^50}║\n"
          f"╚{'═'*50}╝{Style.RESET_ALL}\n")


if __name__ == "__main__":
    sys.exit(cli())
