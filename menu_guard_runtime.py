import logging

import invoice_control_runtime as control

app = control.app
legacy = control.legacy
logger = logging.getLogger(__name__)

_previous_handle_update = legacy.handle_update

MAIN_MENU_COMMANDS = {
    "/start",
    "📝 Nouvelle offre",
    "📁 Convertir une offre en projet",
    "📷 Envoyer une photo",
    "📋 Coller un texte",
    "❓ Aide",
    "❌ Annuler",
}


def _clear_invoice_input_state(uid):
    uid = str(uid)
    session = legacy.user_data.get(uid, {})
    changed = False
    for key in (
        "waiting_invoice_contract_amount",
        "waiting_invoice_percentage",
        "waiting_invoice_amount",
        "pending_invoice",
        "selected_onedrive_project",
        "invoice_project_choices",
    ):
        if key in session:
            session.pop(key, None)
            changed = True
    if changed:
        legacy.user_data[uid] = session
        legacy.save_user_data()
        logger.info("Invoice input state cleared for main-menu command uid=%s", uid)


def handle_update_menu_guard(data):
    msg = data.get("message") or {}
    if msg:
        text = str(msg.get("text") or "").strip()
        actor_id = msg.get("from", {}).get("id")
        if actor_id is not None and text in MAIN_MENU_COMMANDS:
            _clear_invoice_input_state(actor_id)
    return _previous_handle_update(data)


legacy.handle_update = handle_update_menu_guard
logger.info("MAIN MENU GUARD ACTIVE")
