import tempfile
from datetime import date, datetime

from project_followup import ProjectStore, attention_reason, default_project, is_open, update_project


def test_completed_project_is_closed_and_forced_to_100_percent():
    project = update_project(default_project("P26-001-STR-Test"), status="completed")
    assert project["progress"] == 100
    assert not is_open(project)


def test_attention_combines_deadline_blocker_and_stale_update():
    project = default_project("P26-002-STR-Test", now=datetime(2026, 8, 1, 9))
    project.update({"due_date": "2026-08-29", "blocker": "client"})
    reason = attention_reason(project, today=date(2026, 8, 30), now=datetime(2026, 8, 30, 9))
    assert "dépassée de 1 j" in reason
    assert "Client" in reason
    assert "29 j" in reason


def test_store_persists_project_updates():
    path = tempfile.mktemp(prefix="metra-projects-", suffix=".json")
    store = ProjectStore(path)
    store.upsert("P26-003-CIV-Test", progress=50, next_action="drawings")
    loaded = store.load()["projects"]["P26-003-CIV-Test"]
    assert loaded["progress"] == 50
    assert loaded["next_action"] == "drawings"
