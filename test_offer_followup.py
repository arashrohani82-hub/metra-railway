import tempfile
from datetime import date

from offer_followup import FollowupStore, followup_stage, is_due, mark_followed


def test_followup_stages_are_three_seven_and_fourteen_days():
    today = date(2026, 8, 30)
    assert followup_stage("2026-08-28", today)["stage"] == 0
    assert followup_stage("2026-08-27", today)["stage"] == 1
    assert followup_stage("2026-08-23", today)["stage"] == 2
    assert followup_stage("2026-08-16", today)["stage"] == 3


def test_mark_followed_delays_next_internal_reminder_three_days():
    today = date(2026, 8, 30)
    state = mark_followed({}, today)
    offer = {"status": "In process", "date": "2026-08-01"}
    assert state["next_followup_on"] == "2026-09-02"
    assert not is_due(offer, state, date(2026, 9, 1))
    assert is_due(offer, state, date(2026, 9, 2))


def test_followup_store_persists_count():
    store = FollowupStore(tempfile.mktemp(prefix="metra-offers-", suffix=".json"))
    store.mark_followed("ODS26-101", date(2026, 8, 30))
    store.mark_followed("ODS26-101", date(2026, 9, 2))
    assert store.load()["offers"]["ODS26-101"]["followup_count"] == 2
