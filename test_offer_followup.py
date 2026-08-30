import tempfile
from datetime import date

from offer_followup import FollowupStore, followup_stage, mark_followed


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
