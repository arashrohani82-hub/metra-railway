"""Regression coverage for the deployed ODS webhook's menu and old buttons."""

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="metra-menu-test-"))

import app
import ods_runtime
import runtime


def test_facturation_reply_opens_onedrive_project_selector_after_start():
    user_id = 987654321
    with patch.object(app, "ALLOWED_USERS", {user_id}), \
         patch.object(app, "tg"), \
         patch.object(app, "save_user_data"), \
         patch.object(ods_runtime, "show_onedrive_projects_for_invoice") as projects:
        runtime.department_dispatch({"message": {
            "from": {"id": user_id}, "chat": {"id": user_id}, "text": "/start",
        }})
        runtime.department_dispatch({"message": {
            "from": {"id": user_id}, "chat": {"id": user_id}, "text": "🧾 Facturation",
        }})
        projects.assert_called_once_with(user_id, str(user_id))


def test_old_project_button_after_start_opens_offer_list():
    user_id = 987654322
    app.user_data.pop(str(user_id), None)
    with patch.object(app, "ALLOWED_USERS", {user_id}), \
         patch.object(app.req, "post"), \
         patch.object(app, "show_pending_offers") as offers:
        runtime.department_dispatch({"callback_query": {
            "id": "old-button", "data": "project_create",
            "from": {"id": user_id}, "message": {"chat": {"id": user_id}},
        }})
        offers.assert_called_once_with(user_id, str(user_id))


def test_invoice_project_selection_reaches_onedrive_invoice_flow():
    user_id = 987654323
    with patch.object(app, "ALLOWED_USERS", {user_id}), \
         patch.object(app.req, "post"), \
         patch.object(ods_runtime, "select_onedrive_project") as select:
        runtime.department_dispatch({"callback_query": {
            "id": "invoice-project", "data": "od_invoice_project:2",
            "from": {"id": user_id}, "message": {"chat": {"id": user_id}},
        }})
        select.assert_called_once_with(user_id, str(user_id), "2")
