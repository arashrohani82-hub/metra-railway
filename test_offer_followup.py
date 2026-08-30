import tempfile
from datetime import date

from offer_followup import FollowupStore, followup_stage, is_due, mark_followed


def test_followup_stages_are_monthly():
    today = date(2026, 8, 30)
    assert followup_stage("2026-08-01", today)["stage"] == 0
    assert followup_stage("2026-07-31", today)["stage"] == 1
    assert followup_stage("2026-07-01", today)["stage"] == 2
    assert followup_stage("2026-06-01", today)["stage"] == 3


def test_mark_followed_delays_next_internal_reminder_thirty_days():
    today = date(2026, 8, 30)
    state = mark_followed({}, today)
    offer = {"status": "In process", "date": "2026-08-01"}
    assert state["next_followup_on"] == "2026-09-29"
    assert not is_due(offer, state, date(2026, 9, 28))
    assert is_due(offer, state, date(2026, 9, 29))


def test_followup_store_persists_count():
    store = FollowupStore(tempfile.mktemp(prefix="metra-offers-", suffix=".json"))
    store.mark_followed("ODS26-101", date(2026, 8, 30))
    store.mark_followed("ODS26-101", date(2026, 9, 2))
    assert store.load()["offers"]["ODS26-101"]["followup_count"] == 2
