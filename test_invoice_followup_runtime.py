import os
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import runtime
import invoice_followup_runtime as followup


def test_final_reminder_from_menu_requires_confirmation_and_cannot_repeat(monkeypatch, tmp_path):
    user = 82641
    invoice = {"filename": "FAC26-005_P26-015-ABC.pdf", "client": "Marie Dupont",
               "email": "client@example.com", "total": "1000", "remaining": "750"}
    project = {"name": "P26-015-ABC", "client_name": invoice["client"]}
    messages, posts = [], []
    monkeypatch.setattr(followup.legacy, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(followup.legacy, "ALLOWED_USERS", {user})
    monkeypatch.setattr(followup.legacy, "tg", lambda *args, **kwargs: messages.append(args))
    monkeypatch.setattr(followup.legacy, "graph_access_token", lambda: "test")
    monkeypatch.setattr(followup.legacy.req, "post",
                        lambda url, **kwargs: posts.append((url, kwargs)) or SimpleNamespace(status_code=202))
    monkeypatch.setattr(followup.ods_runtime, "onedrive_projects", lambda: [project])
    monkeypatch.setattr(followup.ods_runtime, "projects_awaiting_settlement", lambda items, **kwargs: items)
    monkeypatch.setattr(followup.receipts, "open_project_invoices", lambda folder: [invoice])
    monkeypatch.setattr(followup.receipts, "invoice_records", lambda invoice: [{"amount": "250"}])
    monkeypatch.setattr(followup.receipts, "today", lambda: date(2026, 11, 25))
    monkeypatch.setattr(runtime, "refresh_reply_keyboard", lambda chat: None)

    message = {"chat": {"id": user, "type": "private"}, "from": {"id": user}}

    def click(row=0, col=0):
        action = messages[-1][2][row][col]["callback_data"]
        update = {"callback_query": {"message": message, "from": message["from"], "data": action}}
        runtime.department_dispatch(update)
        return update

    runtime.department_dispatch({"message": {**message, "text": followup.BUTTON}})
    click()  # Project
    click()  # Invoice
    click(3)  # Final reminder
    assert "trois relances" in messages[-1][1]
    assert "750,00 $ CAD" in messages[-1][1]
    assert "2026-11-30" in messages[-1][1]
    assert not posts
    click(1, 0)  # Three-day deadline
    assert "2026-11-28" in messages[-1][1]
    confirm = click()
    runtime.department_dispatch(confirm)
    assert len(posts) == 1
    mail = posts[0][1]["json"]["message"]
    assert mail["toRecipients"] == [{"emailAddress": {"address": invoice["email"]}}]
    assert "2026-11-28" in mail["body"]["content"]
    assert "déjà été envoyée" in messages[-1][1]
