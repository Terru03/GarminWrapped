import contextlib
import csv
from datetime import date
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_cli import load_report


class FixtureClient:
    """Synthetic responses; missing methods exercise normal API fallbacks."""
    def __init__(self, activities):
        self.activities = activities

    def get_activities(self, start, limit):
        assert limit == 100
        return self.activities if start == 0 else []

    def get_daily_steps(self, start, end):
        assert (start, end) == ("2024-01-01", "2024-12-31")
        return [{"calendarDate": "2024-01-01", "totalSteps": 5000},
                {"calendarDate": "2024-01-02", "totalSteps": 10000}]

    def get_sleep_data(self, day):
        return {"dailySleepDTO": {"sleepTimeSeconds": 28800,
                                  "sleepScores": {"overall": {"value": 80}}}} if day == "2024-01-01" else {}

    def get_user_summary(self, day):
        return {"totalKilocalories": 2000, "activeKilocalories": 500,
                "floorsAscended": 3, "moderateIntensityMinutes": 10,
                "vigorousIntensityMinutes": 5} if day == "2024-01-01" else {}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.report = load_report()

    def generate(self, activities, directory):
        original = Path.cwd()
        try:
            os.chdir(directory)
            with patch.object(self.report, "login_garmin", side_effect=AssertionError("account reached")):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.report.main(2024, api=FixtureClient(activities), today=date(2026, 10, 13))
        finally:
            os.chdir(original)

    def test_real_generation_matches_hand_derived_totals_and_existing_filenames(self):
        activities = [
            {"startTimeLocal": "2024-01-01 09:00:00", "activityType": {"typeKey": "running"},
             "distance": 5000, "duration": 1800, "elevationGain": 100},
            {"startTimeLocal": "2024-02-01 09:00:00", "activityType": {"typeKey": "running"},
             "distance": 10000, "duration": 3600, "elevationGain": 200},
            {"startTimeLocal": "2024-02-02 09:00:00", "activityType": {"typeKey": "incident_detected"},
             "distance": 999999, "duration": 999999, "elevationGain": 999999},
            {"startTimeLocal": "2023-01-01 09:00:00", "distance": 999999},
        ]
        with tempfile.TemporaryDirectory() as directory:
            self.generate(activities, directory)
            root = Path(directory)
            self.assertEqual({path.name for path in root.iterdir()}, {
                "garmin_wrapped_2024_report.html", "garmin_wrapped_2024_report.txt",
                "garmin_wrapped_2024_monthly.csv", "garmin_wrapped_2024_by_sport.csv",
                "garmin_wrapped_2024_activities_raw.csv", "garmin_wrapped_2024_wellness_raw.json",
                "garmin_wrapped_2024_wellness_parsed.csv"})
            text = (root / "garmin_wrapped_2024_report.txt").read_text(encoding="utf-8")
            for expected in ["Total Activities: 2", "15.0 km", "1.5 hours", "300 m",
                             "15,000 steps", "7,500/day", "2/366 days", "2,000 kcal",
                             "500 kcal", "3 floors", "20 min", "No data available"]:
                self.assertIn(expected, text)
            html = (root / "garmin_wrapped_2024_report.html").read_text(encoding="utf-8")
            for expected in ["Garmin Wrapped 2024", "15.0", "15,000", "Running", "8.00 hrs"]:
                self.assertIn(expected, html)
            with (root / "garmin_wrapped_2024_monthly.csv").open(newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual([(row["month"], float(row["distance_km"]), float(row["duration_h"]),
                               float(row["elev_m"])) for row in rows],
                             [("2024-01", 5.0, 0.5, 100.0), ("2024-02", 10.0, 1.0, 200.0)])
            with (root / "garmin_wrapped_2024_wellness_parsed.csv").open(newline="") as file:
                wellness = list(csv.DictReader(file))
            self.assertEqual(len(wellness), 366)
            self.assertEqual(float(wellness[0]["steps"]), 5000)
            self.assertEqual(float(wellness[0]["sleep_hours"]), 8)
            self.assertEqual(float(wellness[0]["sleep_score"]), 80)
            self.assertEqual(wellness[2]["steps"], "")
            self.assertEqual(wellness[0]["stress"], "")
            raw = json.loads((root / "garmin_wrapped_2024_wellness_raw.json").read_text(encoding="utf-8"))
            self.assertEqual(raw[0]["date"], "2024-01-01")
            self.assertEqual(raw[-1]["date"], "2024-12-31")

    def test_missing_activity_numbers_still_generate_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            self.generate([{"startTimeLocal": "2024-01-01 09:00:00"}], directory)
            text = (Path(directory) / "garmin_wrapped_2024_report.txt").read_text(encoding="utf-8")
            self.assertIn("Total Activities: 1", text)
            self.assertIn("0.0 km", text)

    def test_empty_or_only_excluded_activities_still_report_wellness(self):
        for activities in [[], [{"startTimeLocal": "2024-01-01 09:00:00",
                                  "activityType": {"typeKey": "incident_detected"},
                                  "distance": 0, "duration": 0, "elevationGain": 0}]]:
            with self.subTest(activities=activities), tempfile.TemporaryDirectory() as directory:
                self.generate(activities, directory)
                text_path = Path(directory) / "garmin_wrapped_2024_report.txt"
                self.assertTrue(text_path.exists(), "Missing activities must not discard wellness reports")
                text = text_path.read_text(encoding="utf-8")
                self.assertIn("Total Activities: 0", text)
                self.assertIn("15,000 steps", text)

    def test_current_year_excludes_activities_after_today(self):
        activities = [{"startTimeLocal": "2024-01-01 09:00:00", "distance": 1000},
                      {"startTimeLocal": "2024-01-02 09:00:00", "distance": 99000}]
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.report.main(2024, api=FixtureClient(activities), today=date(2024, 1, 1))
                text = (Path(directory) / "garmin_wrapped_2024_report.txt").read_text(encoding="utf-8")
                self.assertIn("Period: 2024-01-01 to 2024-01-01", text)
                self.assertIn("Total Activities: 1", text)
                self.assertIn("1.0 km", text)
            finally:
                os.chdir(original)


class ParsingTests(unittest.TestCase):
    def test_nested_and_missing_wellness_shapes(self):
        report = load_report()
        for value, expected in [([{"steps": 100}, {"steps": 250}], 350),
                                ({"totalSteps": 0}, 0), ([10, 20, 30], 60), ({}, None)]:
            self.assertEqual(report.find_steps(value), expected)
        self.assertEqual(report.find_best_sleep_seconds({"sleepTimeMinutes": 90}), 5400)
        self.assertIsNone(report.find_best_sleep_seconds({}))
        self.assertEqual(report.find_body_battery({"high": 90, "low": 20}), (90, 20))
        self.assertEqual(report.find_body_battery(None), (None, None))
        self.assertEqual(report.find_sleep_score({"dailySleepDTO": {"sleepScores": {"overall": {"value": 75}}}}), 75)
        self.assertIsNone(report.find_sleep_score(None))
        self.assertEqual(report.normalise_activity_type({"typeKey": "other"}, "Evening football"), "soccer")


if __name__ == "__main__":
    unittest.main()
