import io
import os
import tempfile
from unittest.mock import patch

import openpyxl
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-balance-test-"))

import app
import ods_runtime as ods


def register(rows):
    wb = openpyxl.Workbook()
    sh = wb.active
    sh.title = "Control Project "
    sh.append(["No", "Year", "Project No", "Project", "Price(CAD)", "status",
               "Physical % Complet", "Financial % Complet", "Accounts Receivable (Now)",
               "Potential Remaining Receivable", "status"])
    for code, state, financial, paid in rows:
        sh.append([None, 2026, code, None, None, state, None, financial, None, None, paid])
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def test_live_settlements_override_invoice_list_without_hiding_exception():
    rows = [(f"P26-{i:03d}", "Cancelled" if i==7 else None, None if i==23 else 1,
             None if i==23 else "Paid") for i in range(1,32)]
    rows.append(("P26-038", "Cancelled", None, None))
    projects = [{"name": f"P26-{i:03d}-ABC"} for i in range(1,50)]
    with patch.object(app,"microsoft_email_config",return_value={"EMAIL_SENDER":"owner"}), \
         patch.object(app,"graph_access_token",return_value="token"), \
         patch.object(app,"download_onedrive_path",return_value=register(rows)), \
         patch.object(app,"list_onedrive_children") as invoices:
        result = ods.projects_awaiting_settlement(projects)
    assert [p["name"] for p in result] == [p["name"] for p in projects
        if int(p["name"][4:7])==23 or (int(p["name"][4:7])>31 and int(p["name"][4:7])!=38)]
    invoices.assert_not_called()


def test_blank_financial_status_is_retained_and_paid_is_explicit():
    projects=[{"name":"P26-023-4HE"},{"name":"P26-032-VDB"},{"name":"P26-034-_STR_XWW"}]
    with patch.object(app,"microsoft_email_config",return_value={"EMAIL_SENDER":"owner"}), \
         patch.object(app,"graph_access_token",return_value="token"), \
         patch.object(app,"download_onedrive_path",return_value=register([
             ("P26-023",None,None,None),("P26-032",None,0,"Paid")])):
        assert ods.projects_awaiting_settlement(projects)==[projects[0],projects[2]]


def test_filter_before_limit_and_clear_stale_choices_on_empty_list():
    projects = [{"name": f"P26-{i:03d}-ABC"} for i in range(40)]
    uid = "test-receivables"
    app.user_data[uid] = {"invoice_project_choices": {"1": {"folder": "old"}}}
    with patch.object(ods, "onedrive_projects", return_value=projects), \
         patch.object(ods, "projects_awaiting_settlement", return_value=[]) as filter_projects, \
         patch.object(app, "save_user_data"), patch.object(app, "tg") as tg:
        ods.show_onedrive_projects_for_invoice(1, uid)
    filter_projects.assert_called_once_with(projects)
    assert app.user_data[uid]["invoice_project_choices"] == {}
    assert "Aucun projet non soldé" in tg.call_args.args[1]
    assert tg.call_args.args[2][0][0]["callback_data"] == "od_invoice_project:all"


def test_new_invoice_keeps_access_to_all_projects():
    with patch.object(ods, "show_onedrive_projects_for_invoice") as show:
        ods.select_onedrive_project(1, "user", "all")
    show.assert_called_once_with(1, "user", only_outstanding=False)


def test_read_failure_does_not_claim_everything_is_paid():
    with patch.object(ods, "onedrive_projects", return_value=[{"name":"P26-001-ABC"}]), \
         patch.object(ods, "projects_awaiting_settlement", side_effect=ValueError("Unreadable register")), \
         patch.object(app, "tg") as tg:
        ods.show_onedrive_projects_for_invoice(1, "user")
    assert "Impossible" in tg.call_args.args[1]
    assert "Aucun projet" not in tg.call_args.args[1]
