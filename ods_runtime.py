import logging
from datetime import datetime

import requests

import fixed_ods_app as base

app = base.app
legacy = base.legacy
logger = logging.getLogger(__name__)

PUBLIC_URL = "https://web-production-c7adbe.up.railway.app"
WEBHOOK_URL = f"{PUBLIC_URL}/webhook/telegram"


def force_telegram_webhook():
    token = getattr(legacy, "BOT_TOKEN", None)
    if not token:
        logger.error("ODS RUNTIME: TELEGRAM_BOT_TOKEN is missing")
        return

    try:
        me = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        ).json()
        if me.get("ok"):
            result = me.get("result") or {}
            logger.info(
                "ODS RUNTIME TELEGRAM BOT: ok=true username=@%s id=%s",
                result.get("username", ""),
                result.get("id", ""),
            )
        else:
            logger.error(
                "ODS RUNTIME TELEGRAM BOT: ok=false error=%s",
                me.get("description", "unknown Telegram error"),
            )
            return

        payload = {
            "url": WEBHOOK_URL,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }
        secret = getattr(legacy, "WEBHOOK_SECRET", "")
        if secret:
            payload["secret_token"] = secret

        result = requests.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json=payload,
            timeout=15,
        ).json()
        logger.info(
            "ODS RUNTIME SET WEBHOOK: ok=%s url=%s description=%s",
            result.get("ok"),
            WEBHOOK_URL,
            result.get("description", ""),
        )
    except Exception:
        logger.exception("ODS RUNTIME WEBHOOK SETUP FAILED")


def _find_history_by_project_folder(folder_name):
    """Recover project metadata from any persisted offer-history record when available."""
    for _owner_uid, records in legacy.offers_history.items():
        for ref, record in (records or {}).items():
            data = record.get("data") or {}
            folder = record.get("project_folder") or data.get("project_folder") or ""
            if folder == folder_name:
                return ref, record
    return None, None


def onedrive_projects():
    """Use OneDrive Projects as the source of truth for invoice project selection."""
    config = legacy.microsoft_email_config()
    token = legacy.graph_access_token()
    sender = config["EMAIL_SENDER"]
    year = datetime.now().strftime("%Y")
    root = f"Metra Structure Inc/Projects/{year}"
    items = legacy.list_onedrive_children(token, sender, root)
    projects = [
        item for item in items
        if item.get("folder") is not None
        and str(item.get("name") or "").upper().startswith(f"P{year[-2:]}-")
    ]
    projects.sort(key=lambda item: str(item.get("name") or ""), reverse=True)
    return projects


def show_onedrive_projects_for_invoice(chat_id, uid):
    uid = str(uid)
    try:
        projects = onedrive_projects()
    except Exception as exc:
        logger.exception("Unable to list OneDrive projects for invoicing")
        legacy.tg(chat_id, f"❌ Impossible de lire les projets OneDrive : {exc}")
        return

    if not projects:
        legacy.tg(chat_id, "Aucun projet n'a été trouvé dans OneDrive / Projects.")
        return

    session = legacy.user_data.get(uid, {})
    choices = {}
    rows = []
    for index, item in enumerate(projects[:30], start=1):
        folder = str(item.get("name") or "").strip()
        choices[str(index)] = {
            "folder": folder,
            "web_url": item.get("webUrl") or "",
        }
        rows.append([{
            "text": folder[:62],
            "callback_data": f"od_invoice_project:{index}",
        }])

    session["invoice_project_choices"] = choices
    legacy.user_data[uid] = session
    legacy.save_user_data()
    text = "🧾 Facturation\n\nChoisissez le projet à facturer :"
    if len(projects) > 30:
        text += "\n(30 projets les plus récents sont affichés.)"
    legacy.tg(chat_id, text, rows)


def select_onedrive_project(chat_id, uid, choice_id):
    uid = str(uid)
    session = legacy.user_data.get(uid, {})
    choice = (session.get("invoice_project_choices") or {}).get(str(choice_id))
    if not choice:
        legacy.tg(chat_id, "❌ Projet introuvable. Ouvrez de nouveau Facturation.")
        return

    folder = choice["folder"]
    ref, record = _find_history_by_project_folder(folder)
    if record:
        data = legacy.history_data_copy(record.get("data") or {})
        data["project_folder"] = folder
        data["project_web_url"] = choice.get("web_url") or record.get("project_web_url") or ""
        data["project_created"] = True
        data["selected_offer_ref"] = ref
    else:
        # Older/test projects can exist in OneDrive even when Railway local history
        # has been lost. Keep the project selectable and ask only for the contract
        # amount needed to calculate a percentage invoice.
        data = {
            "project_folder": folder,
            "project_web_url": choice.get("web_url") or "",
            "project_created": True,
            "price": 0,
            "name": "",
            "email": "",
        }

    data["pending_invoice"] = None
    data["waiting_invoice_percentage"] = False
    data["waiting_invoice_amount"] = False
    data.pop("invoice_project_choices", None)
    legacy.user_data[uid] = data
    legacy.save_user_data()

    if float(data.get("price") or 0) <= 0:
        data["waiting_invoice_contract_amount"] = True
        legacy.user_data[uid] = data
        legacy.save_user_data()
        legacy.tg(
            chat_id,
            f"✅ Projet sélectionné : {folder}\n\n"
            "💰 Quel est le montant total du contrat avant taxes?\n"
            "Exemple : 5500",
        )
        return

    base.show_invoice_options_multi(chat_id, uid)


_original_handle_update = legacy.handle_update


def handle_update_runtime(data):
    """Route invoicing project selection through OneDrive; delegate all other ODS actions."""
    try:
        msg = data.get("message", {})
        cb = data.get("callback_query", {})

        if msg:
            actor_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")
            text = msg.get("text", "")

            if text in ("🧾 Facturation", "🧾 Facturer un projet"):
                if actor_id not in legacy.ALLOWED_USERS:
                    if chat_id:
                        legacy.tg(chat_id, "⛔ Ce bot est privé.")
                    return
                show_onedrive_projects_for_invoice(chat_id, str(actor_id))
                return

            uid = str(actor_id) if actor_id is not None else ""
            session = legacy.user_data.get(uid, {})
            if text and session.get("waiting_invoice_contract_amount"):
                try:
                    amount = float(
                        text.strip().replace("$", "").replace(" ", "").replace(",", "")
                    )
                    if amount <= 0:
                        raise ValueError
                    session["price"] = amount
                    session["waiting_invoice_contract_amount"] = False
                    legacy.user_data[uid] = session
                    legacy.save_user_data()
                    base.show_invoice_options_multi(chat_id, uid)
                except Exception:
                    legacy.tg(chat_id, "❌ Montant invalide. Exemple : 5500")
                return

        if cb:
            cdata = cb.get("data", "")
            if cdata.startswith("od_invoice_project:"):
                actor_id = cb.get("from", {}).get("id")
                chat_id = cb.get("message", {}).get("chat", {}).get("id")
                if actor_id not in legacy.ALLOWED_USERS:
                    if chat_id:
                        legacy.tg(chat_id, "⛔ Ce bot est privé.")
                    return
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cb.get("id")},
                        timeout=3,
                    )
                except Exception:
                    pass
                select_onedrive_project(
                    chat_id,
                    str(actor_id),
                    cdata.split(":", 1)[1],
                )
                return
    except Exception:
        logger.exception("ODS runtime invoice routing failed")

    return _original_handle_update(data)


legacy.handle_update = handle_update_runtime
logger.info("ODS RUNTIME ONEDRIVE INVOICE PROJECT LIST ACTIVE")

force_telegram_webhook()
