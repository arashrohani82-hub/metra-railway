import os
import io
import tempfile
from datetime import datetime
from unittest.mock import patch

import openpyxl

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-ods-list-test-"))

import app


HEADERS = [
    "No", "Year ", "Month", "Description", "Price($)", "Date", "Status",
    "Accepted Price", "Source", "Contact", "Date of acceptation", "Email",
]


def workbook_with_ods_sheet():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "data 2026"
    sheet.append(HEADERS)
    sheet.append([
        1, 2026, "August", "ODS26-001-AAA-Existing", 1000,
        datetime(2026, 8, 1), "In process", 0, "Connection", "Existing", None,
        "existing@example.com",
    ])
    return workbook


def test_offer_is_inserted_once_using_full_ods_reference():
    workbook = workbook_with_ods_sheet()
    data = {
        "odsNum": "ODS26-098-RES-Correction-de-plans",
        "price": 2500,
        "name": "Mme Christine Vaitekunas",
        "email": "client@example.com",
        "email_sent_at": "2026-08-19T14:00:00",
    }

    first_row = app.upsert_ods_list_workbook(workbook, data, "In process")
    second_row = app.upsert_ods_list_workbook(workbook, data, "In process")

    assert first_row == second_row == 3
    assert workbook["data 2026"].max_row == 3
    assert workbook["data 2026"]["D3"].value.startswith("ODS26-098-RES")
    assert workbook["data 2026"]["G3"].value == "In process"


def test_project_conversion_marks_offer_accepted():
    workbook = workbook_with_ods_sheet()
    data = {
        "odsNum": "ODS26-099-AGR-Agrandissement",
        "price": 2800,
        "name": "Veronique De Foy",
        "email": "ceo@example.com",
        "email_sent_at": "2026-08-19T14:00:00",
    }
    app.upsert_ods_list_workbook(workbook, data, "In process")
    accepted_at = datetime(2026, 8, 28, 10, 30)

    row = app.upsert_ods_list_workbook(workbook, data, "Accept", accepted_at)
    sheet = workbook["data 2026"]

    assert row == 3
    assert sheet["G3"].value == "Accept"
    assert sheet["H3"].value == 2800
    assert sheet["K3"].value == accepted_at


def test_project_conversion_records_project_folder_for_guardian_sync():
    workbook = workbook_with_ods_sheet()
    data = {
        "odsNum": "ODS26-100-STR-Plans-structuraux",
        "project_folder": "P26-031-STR-Plans-structuraux",
        "price": 4200,
        "name": "Client Test",
    }
    row = app.upsert_ods_list_workbook(workbook, data, "Accept")
    sheet = workbook["data 2026"]
    headers = {str(cell.value or "").strip(): cell.column for cell in sheet[1]}

    assert sheet.cell(row, headers["Project Code"]).value == data["project_folder"]


def test_missing_calculation_properties_are_repaired_before_save():
    workbook = workbook_with_ods_sheet()
    workbook.calculation = None
    data = {
        "odsNum": "ODS26-107-GGH-Évaluation-structurale-des-fondations",
        "price": 1800,
        "name": "Nevin El-Tahry",
        "email": "nevin.i.reda@gmail.com",
        "email_sent_at": "2026-08-31T11:51:00",
    }

    row = app.upsert_ods_list_workbook(workbook, data, "In process")
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    reopened = openpyxl.load_workbook(output)

    assert row == 3
    assert reopened.calculation is not None
    assert reopened.calculation.fullCalcOnLoad is True
    assert reopened.calculation.forceFullCalc is True
    assert reopened.calculation.calcMode == "auto"
    assert reopened["data 2026"]["D3"].value.startswith("ODS26-107-GGH")


def test_locked_list_is_refetched_and_other_editor_change_is_preserved():
    original = workbook_with_ods_sheet()
    changed = workbook_with_ods_sheet()
    changed['data 2026'].append([
        2, 2026, 'September', 'ODS26-097-CIV-Other-editor', 1000,
        datetime(2026, 9, 1), 'In process', 0, '', 'Someone else', None, '',
    ])

    def content(workbook):
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    writes = []
    def upload(_token, _sender, _path, payload, _mime):
        writes.append(payload)
        if len(writes) == 1:
            raise app.OneDriveUploadError(app.ODS_LIST_PATH, 423)

    data = {
        'odsNum': 'ODS26-098-CIV-ICK-Plan-de-drainage',
        'price': 6500, 'name': 'Cédric Théoret',
        'email': 'cedrict@aquawatereau.com',
        'email_sent_at': '2026-09-24T14:39:00',
    }
    with patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'test@example.com'}), \
         patch.object(app, 'graph_access_token', return_value='token'), \
         patch.object(app, 'download_onedrive_path', side_effect=[content(original), content(changed)]) as download, \
         patch.object(app, 'upload_onedrive_path', side_effect=upload), \
         patch.object(app.time, 'sleep'):
        row = app.sync_ods_list(data)

    saved = openpyxl.load_workbook(io.BytesIO(writes[-1]))['data 2026']
    assert download.call_count == 2
    assert row == 4
    assert saved['D3'].value == 'ODS26-097-CIV-Other-editor'
    assert saved['D4'].value.startswith('ODS26-098-CIV-ICK')


def test_permanent_lock_exposes_manual_retry_message():
    buffer = io.BytesIO()
    workbook_with_ods_sheet().save(buffer)
    data = {'odsNum': 'ODS26-098-CIV-ICK-Test', 'price': 6500, 'name': 'Client'}
    with patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'test@example.com'}), \
         patch.object(app, 'graph_access_token', return_value='token'), \
         patch.object(app, 'download_onedrive_path', return_value=buffer.getvalue()), \
         patch.object(app, 'upload_onedrive_path', side_effect=app.OneDriveUploadError(app.ODS_LIST_PATH, 423)), \
         patch.object(app.time, 'sleep'):
        try:
            app.sync_ods_list(data)
        except RuntimeError as exc:
            assert 'Réessayer List.xlsx' in str(exc)
        else:
            raise AssertionError('Permanent lock must be reported')


def test_reconciliation_recovers_missing_recent_offer_without_resending_email():
    workbook = workbook_with_ods_sheet()
    buffer = io.BytesIO()
    workbook.save(buffer)
    ref = 'ODS26-128-STR-CJH'
    uid = '987654320'
    record = {
        'sent_at': datetime.now().isoformat(),
        'status': 'In process',
        'data': {'odsNum': ref + '-Étude-du-fonds-de-prévoyance',
                 'email_sent_at': datetime.now().isoformat(), 'price': 2800},
    }
    with patch.dict(app.offers_history, {uid: {ref: record}}, clear=True), \
         patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'test@example.com'}), \
         patch.object(app, 'graph_access_token', return_value='token'), \
         patch.object(app, 'download_onedrive_path', return_value=buffer.getvalue()), \
         patch.object(app, 'sync_ods_list') as sync, \
         patch.object(app, 'save_offers_history'):
        app.reconcile_recent_ods_list()
        sync.assert_called_once_with(record['data'], 'In process')
        assert record['list_sync_pending'] is False

        # Once the row exists, later cycles do not write it again.
        workbook['data 2026'].append([2, 2026, 'September', ref, 2800])
        fresh = io.BytesIO()
        workbook.save(fresh)
        with patch.object(app, 'download_onedrive_path', return_value=fresh.getvalue()):
            app.reconcile_recent_ods_list()
        sync.assert_called_once()


def test_reconciliation_keeps_locked_offer_pending_for_next_cycle():
    buffer = io.BytesIO()
    workbook_with_ods_sheet().save(buffer)
    ref = 'ODS26-128-STR-CJH'
    record = {
        'sent_at': datetime.now().isoformat(),
        'data': {'odsNum': ref, 'email_sent_at': datetime.now().isoformat()},
    }
    with patch.dict(app.offers_history, {'987654320': {ref: record}}, clear=True), \
         patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'test@example.com'}), \
         patch.object(app, 'graph_access_token', return_value='token'), \
         patch.object(app, 'download_onedrive_path', return_value=buffer.getvalue()), \
         patch.object(app, 'sync_ods_list', side_effect=RuntimeError('423')) as sync, \
         patch.object(app, 'save_offers_history'):
        app.reconcile_recent_ods_list()
        assert record['list_sync_pending'] is True
        app.reconcile_recent_ods_list()
        assert sync.call_count == 2
