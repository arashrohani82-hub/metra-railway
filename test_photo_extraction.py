import os
import tempfile

from pypdf import PdfReader

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-photo-test-"))

import app


def test_multi_image_prompt_requires_all_sources_and_body_identity():
    prompt = app._photo_extraction_prompt(3)
    assert "ALL 3 attached image(s)" in prompt
    assert "every attached building photo" in prompt
    assert "explicit self-identification" in prompt
    assert "phone number" in prompt
    assert "@metrastructure.ca" in prompt


def test_contact_verification_prefers_body_name_and_visible_phone():
    original = {
        "client_name": "Nevin Reda",
        "client_civility": "M./Mme",
        "phone": "",
        "email": "info@metrastructure.ca",
        "address": "",
    }
    verified = {
        "client_name": "Nevin El-Tahry",
        "client_civility": "Mme",
        "phone": "647-282-1365",
        "email": "nevin.i.reda@gmail.com",
        "address": "8391 Avenue de L'Esplanade, Montreal, H2P 2R6",
    }
    merged = app._merge_verified_contacts(original, verified)
    assert merged["client_name"] == "Nevin El-Tahry"
    assert merged["phone"] == "647-282-1365"
    assert merged["email"] == "nevin.i.reda@gmail.com"
    assert merged["address"].startswith("8391 Avenue")


def test_offer_pdf_uses_consultation_branding():
    data = {
        "name": "Nevin El-Tahry",
        "civility": "Mme",
        "phone": "647-282-1365",
        "email": "nevin.i.reda@gmail.com",
        "addr": "8391 Avenue de L'Esplanade, Montreal, H2P 2R6",
        "odsNum": "ODS26-107-GVF-Évaluation-structurale",
        "price": 1800,
        "service": "Évaluation des fissures et désordres structuraux",
        "service_lines": [
            "Inspection visuelle des fissures et désordres observés",
            "Évaluation structurale des éléments accessibles",
            "Rapport présentant les observations et recommandations",
        ],
    }
    pdf = app.generate_pdf(data)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "METRA CONSULTATION INC." in text
    assert "Metra Consultation Inc." in text
    assert "Structure Inc." not in text


def test_service_lines_are_complete_and_never_truncated_with_ellipsis():
    long_line = (
        "Inspection visuelle des fondations à l'intérieur et à l'extérieur, "
        "avec relevé des fissures, déformations et traces d'humidité, incluant…"
    )
    cleaned = app._clean_service_line(long_line)
    assert cleaned.endswith("traces d'humidité")
    assert "…" not in cleaned
    assert "..." not in cleaned
