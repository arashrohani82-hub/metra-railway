import os
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-balance-test-"))

import app
import ods_runtime as ods
import invoice_control_runtime as control
import payment_receipt_runtime as receipts


def test_settled_hidden_partial_visible_and_alphanumeric_code_exact():
    projects = [{"name": name} for name in ("P26-023-4HE-Mur", "P26-024-CLI-Test", "P26-025-LCQ-New")]
    texts = {
        "FAC1.pdf": "Projet: P26-023-4HE\nMontant total : 100.00\nFacturé à :\nClient\nProjet : P26-023-4HE",
        "FAC2.pdf": "Projet: P26-024-CLI\nMontant total : 200.00\nFacturé à :\nClient\nProjet : P26-024-CLI",
        "FAC3.pdf": "Projet: P26-024-CLI\nMontant total : 50.00\nFacturé à :\nClient\nProjet : P26-024-CLI",
    }
    records = {"a": {"invoice": {"filename": "FAC1.pdf"}, "amount": "100"},
               "b": {"invoice": {"filename": "FAC2.pdf"}, "amount": "75"},
               "c": {"invoice": {"filename": "FAC3.pdf"}, "amount": "50"}}
    with patch.object(app, "graph_access_token", return_value="token"), \
         patch.object(app, "list_onedrive_children", return_value=[{"name": n} for n in texts]), \
         patch.object(app, "download_onedrive_path", side_effect=lambda t,o,p: texts[p.rsplit("/",1)[-1]]), \
         patch.object(control, "_pdf_text", side_effect=lambda value: value), \
         patch.object(receipts, "ledger", return_value=records):
        result = ods.projects_with_receivables(projects)
    assert len(result) == 1
    assert result[0]["name"] == "P26-024-CLI-Test"
    assert str(result[0]["receivable"]) == "125.00"


def test_filter_before_limit_and_clear_stale_choices_on_empty_list():
    projects = [{"name": f"P26-{i:03d}-ABC"} for i in range(40)]
    uid = "test-receivables"
    app.user_data[uid] = {"invoice_project_choices": {"1": {"folder": "old"}}}
    with patch.object(ods, "onedrive_projects", return_value=projects), \
         patch.object(ods, "projects_with_receivables", return_value=[]) as filter_projects, \
         patch.object(app, "save_user_data"), patch.object(app, "tg") as tg:
        ods.show_onedrive_projects_for_invoice(1, uid)
    filter_projects.assert_called_once_with(projects)
    assert app.user_data[uid]["invoice_project_choices"] == {}
    assert "Aucun solde" in tg.call_args.args[1]
    assert tg.call_args.args[2][0][0]["callback_data"] == "od_invoice_project:all"


def test_new_invoice_keeps_access_to_projects_without_invoices():
    with patch.object(ods, "show_onedrive_projects_for_invoice") as show:
        ods.select_onedrive_project(1, "user", "all")
    show.assert_called_once_with(1, "user", only_outstanding=False)


def test_read_failure_does_not_claim_everything_is_paid():
    with patch.object(ods, "onedrive_projects", return_value=[{"name":"P26-001-ABC"}]), \
         patch.object(ods, "projects_with_receivables", side_effect=ValueError("Unreadable invoice")), \
         patch.object(app, "tg") as tg:
        ods.show_onedrive_projects_for_invoice(1, "user")
    assert "Impossible" in tg.call_args.args[1]
    assert "Aucun solde" not in tg.call_args.args[1]


def test_balance_listing_does_not_require_invoice_client_block():
    from payment_receipts import invoice_balance_details, invoice_details
    text = "Projet : P26-023-4HE\nMontant total : 114.98"
    assert invoice_balance_details(text, "FAC-test.pdf") == {
        "filename": "FAC-test.pdf", "total": "114.98"}
    # Receipt issuance still requires a verified client block.
    with pytest.raises(ValueError, match="Client de la facture"):
        invoice_details(text, "FAC-test.pdf")
    with patch.object(app, "graph_access_token", return_value="token"), \
         patch.object(app, "list_onedrive_children", return_value=[{"name":"FAC-test.pdf"}]), \
         patch.object(app, "download_onedrive_path", return_value=text), \
         patch.object(control, "_pdf_text", side_effect=lambda value: value), \
         patch.object(receipts, "ledger", return_value={}):
        result = ods.projects_with_receivables([{"name":"P26-023-4HE-Mur"}])
    assert str(result[0]["receivable"]) == "114.98"
