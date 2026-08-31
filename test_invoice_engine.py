from datetime import date

from invoice_engine import (
    generate_invoice_pdf,
    invoice_filename,
    invoice_values,
)


def sample_data():
    return {
        "name": "Christine Vaitekunas",
        "civility": "Mme",
        "addr": "2580 Avenue Parkville\nMontréal, Québec, H1N 3A8",
        "phone": "514-207-4196",
        "email": "client@example.com",
        "price": 2500,
        "project_folder": "P26-030-RES-Correction-de-plans",
        "service_lines": [
            "Révision des plans refusés par la Ville de Montréal",
            "Relevé des dimensions de la fenêtre existante",
            "Conception structurale de la nouvelle ouverture",
        ],
    }


def test_quebec_tax_calculation_matches_invoice_48():
    values = invoice_values(2500, percentage=25)
    assert values["subtotal"] == 625
    assert values["gst"] == 31.25
    assert values["qst"] == 62.34
    assert values["total"] == 718.59


def test_invoice_filename_keeps_invoice_and_project_separate():
    name = invoice_filename(49, sample_data(), date(2026, 8, 21))
    assert name == "FAC26-049_P26-030-RES.pdf"


def test_invoice_filename_accepts_alphanumeric_project_discipline():
    data = {"project_folder": "P26-022-6ZR-Reamenagement"}
    name = invoice_filename(52, data, date(2026, 8, 31))
    assert name == "FAC26-052_P26-022-6ZR.pdf"


def test_invoice_pdf_is_generated():
    pdf, values, due = generate_invoice_pdf(
        sample_data(), 49, percentage=25, logo_path=None,
        invoice_date=date(2026, 8, 21),
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000
    assert values["total"] == 718.59
    assert due.isoformat() == "2026-09-20"
