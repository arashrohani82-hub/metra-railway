"""Older offers visible in List.xlsx must still convert through the follow-up button."""

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-conversion-test-"))

import app
import offer_followup_runtime as followup


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
