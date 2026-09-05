import os
import tempfile
from datetime import datetime

import openpyxl

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-dashboard-test-"))

import dashboard_runtime as dashboard


HEADERS = [
    "No", "Year ", "Month", "Description", "Price($)", "Date", "Status",
    "Accepted Price", "Source", "Contact", "Date of acceptation", "Email",
]


def dashboard_workbook():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "data 2026"
    sheet.append(HEADERS)
    sheet.append([1, 2026, "August", "ODS26-101", 5000, datetime(2026, 8, 2), "Accept", 4500, "Google", "A", None, "a@example.com"])
    sheet.append([2, 2026, "August", "ODS26-102", 3000, datetime(2026, 8, 4), "In process", 0, "Google", "B", None, "b@example.com"])
    sheet.append([3, 2026, "August", "ODS26-103", 2000, datetime(2026, 8, 10), "Refused", 0, "Referral", "C", None, "c@example.com"])
    sheet.append([4, 2026, "July", "ODS26-099", 1000, datetime(2026, 7, 12), "Accept", 1000, "Referral", "D", None, "d@example.com"])
    previous = workbook.create_sheet("data 2025")
    previous.append(HEADERS)
    previous.append([5, 2025, "December", "ODS25-198", 2500, datetime(2025, 12, 8), "Accept", 2500, "Website", "E", None, "e@example.com"])
    return workbook


def test_monthly_dashboard_totals_and_pipeline():
    metrics = dashboard.dashboard_metrics(
        dashboard_workbook(), now=datetime(2026, 8, 30),
    )

    assert metrics["offers"] == 3
    assert metrics["quoted"] == 10000
    assert metrics["accepted"] == 1
    assert metrics["revenue"] == 4500
    assert metrics["conversion"] == 1 / 3
    assert metrics["statuses"]["In process"] == 1
    assert metrics["statuses"]["Refused"] == 1
    assert metrics["stale_count"] == 1


def test_marketing_sources_are_ranked_by_accepted_revenue():
    metrics = dashboard.dashboard_metrics(
        dashboard_workbook(), period="year", marketing=True,
        now=datetime(2026, 8, 30),
    )

    assert metrics["sources"][0][0] == "Google"
    assert metrics["sources"][0][1] == {
        "offers": 2, "accepted": 1, "quoted": 8000.0, "revenue": 4500.0,
    }
    assert "Performance par source" in dashboard.format_dashboard(metrics)
    assert "Attribution basée sur la colonne Source" in dashboard.format_dashboard(metrics)


def test_previous_month_filter():
    metrics = dashboard.dashboard_metrics(
        dashboard_workbook(), period="previous", now=datetime(2026, 8, 30),
    )

    assert metrics["offers"] == 1
    assert metrics["accepted"] == 1
    assert metrics["revenue"] == 1000


def test_any_available_month_can_be_selected():
    metrics = dashboard.dashboard_metrics(
        dashboard_workbook(), period="2025-12", now=datetime(2026, 8, 30),
    )

    assert metrics["period_label"] == "Décembre 2025"
    assert metrics["offers"] == 1
    assert metrics["revenue"] == 2500


def test_available_months_are_newest_first():
    assert dashboard.available_months(dashboard_workbook()) == [
        "2026-08", "2026-07", "2025-12",
    ]


def test_month_picker_and_chart_buttons_are_available():
    buttons = dashboard.dashboard_buttons(period="2026-08")
    callback_data = [button["callback_data"] for row in buttons for button in row]

    assert "ods_dashboard_months:summary:0" in callback_data
    assert "ods_dashboard_chart:summary:2026-08" in callback_data
    assert "ods_dashboard:marketing:2026-08" in callback_data


def test_dashboard_chart_is_a_png():
    metrics = dashboard.dashboard_metrics(
        dashboard_workbook(), period="2026-08", now=datetime(2026, 8, 30),
    )

    assert dashboard.dashboard_chart(metrics).read(8) == b"\x89PNG\r\n\x1a\n"
