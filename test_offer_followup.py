import tempfile
from datetime import date

from offer_followup import FollowupStore, build_followup_email, followup_stage, mark_followed, recommended_followup_day


def test_followup_stages_are_monthly():
    today = date(2026, 8, 30)
    assert followup_stage("2026-08-01", today)["stage"] == 0
    assert followup_stage("2026-07-31", today)["stage"] == 1
    assert followup_stage("2026-07-01", today)["stage"] == 2
    assert followup_stage("2026-06-01", today)["stage"] == 3


def test_mark_followed_only_records_the_manual_action():
    today = date(2026, 8, 30)
    state = mark_followed({}, today)
    assert state["last_followup_at"] == "2026-08-30"
    assert state["followup_count"] == 1
    assert "next_followup_on" not in state


def test_followup_store_persists_count():
    store = FollowupStore(tempfile.mktemp(prefix="metra-offers-", suffix=".json"))
    store.mark_followed("ODS26-101", date(2026, 8, 30))
    store.mark_followed("ODS26-101", date(2026, 9, 2))
    assert store.load()["offers"]["ODS26-101"]["followup_count"] == 2


def test_email_templates_and_recommended_stage():
    offer = {"reference": "ODS26-101-STR", "contact": "Julie Dubé"}
    subject, body = build_followup_email(offer, 15)
    assert subject == "Suivi – Offre de service ODS26-101-STR"
    assert "Bonjour Julie Dubé" in body
    assert "Ingénieur en structure et en génie civil" in body
    assert "valide pendant 30 jours" in body
    assert "fermerons le dossier" not in body
    _, final_body = build_followup_email(offer, 30)
    assert "période de validité de 30 jours" in final_body
    assert "inactive" in final_body
    assert recommended_followup_day(3) == 3
    assert recommended_followup_day(8) == 7
    assert recommended_followup_day(12) == 10
    assert recommended_followup_day(20) == 15
    assert recommended_followup_day(31) == 30
