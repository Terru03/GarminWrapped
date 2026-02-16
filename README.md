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

- [Python 3.13+](https://www.python.org/downloads/)
- A Garmin Connect account

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/garmin-wrapped.git
   cd garmin-wrapped
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *Note: The script will identify missing packages and offer to install them automatically.*

## Usage

1. Run the batch script (Windows):
   ```cmd
   run_garmin_wrapped.bat
   ```

2. Or run the Python script directly:
   ```bash
   python garmin_wrapped_2025_all.py [YEAR]
   ```
   *Example: `python garmin_wrapped_2025_all.py 2024`*

3. Follow the prompts to log in to your Garmin account.

## Output

The script generates:
- `garmin_wrapped_[YEAR]_report.html`: Interactive dashboard
- `garmin_wrapped_[YEAR]_report.txt`: Text summary

## Security Note

This tool runs locally on your machine. Your Garmin credentials are used only to authenticate with the Garmin Connect API and are stored locally in the `.garmin_tokens` directory. **Never share this directory or your credentials.**
