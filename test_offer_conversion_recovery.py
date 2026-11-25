"""Older offers visible in List.xlsx must still convert through the follow-up button."""

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-conversion-test-"))

import app
import offer_followup_runtime as followup
from openpyxl import Workbook


def test_followup_recovers_archived_offer_before_confirmation():
    uid = "987654324"
    offer = {"reference": "ODS26-119-APL"}
    app.offers_history.pop(uid, None)
    def restore(user, reference):
        assert (user, reference) == (uid, offer["reference"])
        app.offers_history[uid] = {reference: {"data": {"odsNum": reference}}}
        return reference

    with patch("ods_recovery._recover_from_xlsx", side_effect=restore) as recover, \
         patch.object(app, "show_offer_conversion_confirmation") as confirm:
        followup._confirm_conversion_from_followup(int(uid), uid, offer)
    recover.assert_called_once()
    confirm.assert_called_once_with(int(uid), uid, offer["reference"])
    app.offers_history.pop(uid, None)


def test_recovered_project_copies_original_offer_files():
    data = {
        "odsNum": "ODS26-119-APL", "project_title": "Mur de soutènement",
        "recovered_from_onedrive": True,
        "recovered_archive_root": "Metra Structure Inc/Offre de service/Structure",
        "recovered_archive_file": "ODS26-119-APL-Mur-de-soutènement.xlsx",
    }
    source = data["recovered_archive_root"]
    files = {f"{source}/ODS26-119-APL-Mur-de-soutènement.{ext}": content
             for ext, content in (("xlsx", b"original-xlsx"), ("pdf", b"original-pdf"))}
    uploads = []
    with patch.object(app, "microsoft_email_config", return_value={"EMAIL_SENDER": "sender@example.com"}), \
         patch.object(app, "graph_access_token", return_value="token"), \
         patch.object(app, "create_onedrive_folder", return_value={"webUrl": "https://example.test/project"}), \
         patch.object(app, "list_onedrive_children", side_effect=[[], [{"name": "ODS26-119-APL-Mur-de-soutènement.pdf"}]]), \
         patch.object(app, "download_onedrive_path", side_effect=lambda _t, _s, path: files[path]), \
         patch.object(app, "upload_onedrive_path", side_effect=lambda _t, _s, path, content, _mime: uploads.append((path, content))), \
         patch.object(app, "generate_pdf", side_effect=AssertionError("Must copy original PDF")), \
         patch.object(app, "generate_excel", side_effect=AssertionError("Must copy original spreadsheet")):
        folder, _ = app.create_project_from_ods(data)
    assert folder.startswith("P26-")
    assert [content for _, content in uploads] == [b"original-pdf", b"original-xlsx"]


def test_discount_reply_previews_exact_agreed_amount_without_creating_project(monkeypatch):
    uid = 987654324
    ref = 'ODS26-161-STR-QHH'
    monkeypatch.setattr(app, 'ALLOWED_USERS', {uid})
    monkeypatch.setattr(app, 'BOT_TOKEN', '12345:test')
    monkeypatch.setitem(app.offers_history, str(uid), {ref: {'data': {'price': 7000}}})
    message = {
        'from': {'id': uid}, 'chat': {'id': uid}, 'text': '6 500,50 $',
        'reply_to_message': {'from': {'id': 12345}, 'text': f'{app.DISCOUNT_PROMPT}{ref}\n'},
    }
    with patch.object(app, 'tg') as tg, patch.object(app.executor, 'submit') as submit:
        assert app.handle_offer_discount({'message': message})
        assert 'Rabais : 499.50 $' in tg.call_args.args[1]
        button = tg.call_args.args[2][0][0]
        assert button['callback_data'] == f'offer_rabais_apply:{ref}:650050'
        submit.assert_not_called()
        message['text'] = '7500'
        assert app.handle_offer_discount({'message': message})
        assert 'inférieur au montant proposé' in tg.call_args.args[1]
        submit.assert_not_called()


def test_discount_preserves_archived_offer_and_sets_register_and_billing(monkeypatch):
    uid = '987654324'
    ref = 'ODS26-161-STR-QHH'
    data = {'odsNum': ref, 'price': 7000, 'email_sent_at': '2026-11-16'}
    folder = 'P26-060-QHH-Projet'
    monkeypatch.setitem(app.offers_history, uid, {ref: {'data': data}})
    monkeypatch.setitem(app.user_data, uid, {})
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'data 2026'
    sheet.append(list(app.ODS_LIST_HEADERS.values()))

    def create_project(offer):
        assert offer['price'] == 7000
        offer['project_folder'] = folder
        return folder, ''

    with patch.object(app, 'create_project_from_ods', side_effect=create_project) as create, \
         patch.object(app, 'sync_ods_list', side_effect=lambda *a, **kw: app.upsert_ods_list_workbook(workbook, *a, **kw)), \
         patch.object(app, 'save_user_data'), patch.object(app, 'save_offers_history'), patch.object(app, 'tg'):
        app.do_create_project(1, uid, ref, '650050')
        app.do_create_project(1, uid, ref, '600000')

    create.assert_called_once()
    values = dict(zip(next(sheet.values), list(sheet.values)[1]))
    assert values['Price($)'] == 7000
    assert values['Accepted Price'] == 6500.50
    assert app.user_data[uid]['price'] == 6500.50
    assert app.offers_history[uid][ref]['data']['quoted_price'] == 7000
