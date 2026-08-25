import logging

import invoice_control_runtime as control

app = control.app
legacy = control.legacy
logger = logging.getLogger(__name__)

_previous_handle_update = legacy.handle_update


def final_main_menu():
    """Single authoritative reply keyboard for the ODS bot."""
    return {
        'keyboard': [
            [{'text': '📝 Nouvelle offre'}],
            [{'text': '📁 Convertir une offre en projet'}],
            [{'text': '🧾 Facturation'}],
            [{'text': '📷 Envoyer une photo'}, {'text': '📋 Coller un texte'}],
            [{'text': '❓ Aide'}, {'text': '❌ Annuler'}],
        ],
        'resize_keyboard': True,
        'is_persistent': True,
        'input_field_placeholder': 'Photo ou texte du client…',
    }


# Make every legacy flow that asks for main_menu() use the same keyboard.
legacy.main_menu = final_main_menu

MAIN_MENU_COMMANDS = {
    "/start",
    "/menu",
    "📝 Nouvelle offre",
    "📁 Convertir une offre en projet",
    "🧾 Facturation",
    "🧾 Facturer un projet",
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
        chat_id = msg.get("chat", {}).get("id")
        if actor_id is not None and text in MAIN_MENU_COMMANDS:
            _clear_invoice_input_state(actor_id)

        # Refresh Telegram's persistent reply keyboard explicitly on /start or /menu.
        # This replaces any stale keyboard cached by Telegram from older deployments.
        if text in ("/start", "/menu") and chat_id:
            if actor_id not in legacy.ALLOWED_USERS:
                legacy.tg(chat_id, "⛔ Ce bot est privé.")
                return
            legacy.tg(
                chat_id,
                "👋 Métra Structure\n\nChoisissez une opération :",
                reply_markup=final_main_menu(),
            )
            return

    return _previous_handle_update(data)


legacy.handle_update = handle_update_menu_guard
logger.info("MAIN MENU GUARD ACTIVE — FACTURATION PERSISTENT")
