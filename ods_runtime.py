import io
import logging
import os
import re
import time
import urllib.parse
from datetime import datetime

import openpyxl
import requests

import fixed_ods_app as base

app = base.app
legacy = base.legacy
logger = logging.getLogger(__name__)

PUBLIC_URL = os.environ.get(
    "ODS_PUBLIC_URL", "https://web-production-c7adbe.up.railway.app"
).strip().rstrip("/")
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

        result = {}
        for attempt in range(3):
            response = requests.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json=payload,
                timeout=15,
            )
            result = response.json() if response.content else {}
            if result.get("ok"):
                break
            retry_after = int((result.get("parameters") or {}).get("retry_after") or 0)
            if response.status_code != 429 and not retry_after:
                break
            if attempt < 2:
                time.sleep(max(1, min(retry_after, 5)))
        logger.info(
            "ODS RUNTIME SET WEBHOOK: ok=%s url=%s description=%s",
            result.get("ok"),
            WEBHOOK_URL,
            result.get("description", ""),
        )
    except Exception:
        logger.exception("ODS RUNTIME WEBHOOK SETUP FAILED")


def _find_history_by_project_folder(folder_name):
    for _owner_uid, records in legacy.offers_history.items():
        for ref, record in (records or {}).items():
            data = record.get("data") or {}
            folder = record.get("project_folder") or data.get("project_folder") or ""
            if folder == folder_name:
                return ref, record
    return None, None


def _strip_label(value, labels):
    text = str(value or "").strip()
    for label in labels:
        if text.lower().startswith(label.lower()):
            return text[len(label):].strip()
    return text


def recover_project_metadata_from_onedrive(folder_name):
    """Recover client/scope details from the ODS Excel archived in Correspondence."""
    try:
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        sender = config["EMAIL_SENDER"]
        year = datetime.now().strftime("%Y")
        correspondence = (
            f"Metra Structure Inc/Projects/{year}/{folder_name}/Correspondence"
        )
        items = legacy.list_onedrive_children(token, sender, correspondence)
        xlsx_items = [
            item for item in items
            if str(item.get("name") or "").lower().endswith(".xlsx")
            and str(item.get("name") or "").upper().startswith("ODS")
        ]
        if not xlsx_items:
            return {}
        xlsx_items.sort(key=lambda item: str(item.get("name") or ""), reverse=True)
        item = xlsx_items[0]
        filename = str(item.get("name") or "")
        relative_path = f"{correspondence}/{filename}"
        encoded_path = urllib.parse.quote(relative_path, safe="/")
        encoded_sender = urllib.parse.quote(sender, safe="")
        response = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{encoded_sender}/drive/"
            f"root:/{encoded_path}:/content",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code != 200:
            logger.warning("ODS metadata download failed: %s %s", response.status_code, filename)
            return {}

        wb = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True)
        ws = wb["ODS"] if "ODS" in wb.sheetnames else wb[wb.sheetnames[0]]
        identity = str(ws["B7"].value or "").strip()
        civility = ""
        name = identity
        m = re.match(r"^(M\.|Mme|M\./Mme)\s+(.*)$", identity, re.I)
        if m:
            civility = m.group(1)
            name = m.group(2).strip()
        address = _strip_label(ws["B8"].value, ["Adresse :", "Adresse:"])
        phone = _strip_label(ws["B9"].value, ["Cell. :", "Cell.:", "Téléphone :", "Téléphone:"])
        email = _strip_label(ws["B10"].value, ["Courriel :", "Courriel:", "Email :", "Email:"])
        description = str(ws["B47"].value or "").strip()
        ods_num = filename.rsplit(".", 1)[0]

        def clean_placeholder(value):
            text = str(value or "").strip()
            return "" if text in ("À compléter", "À confirmer", "—", "None") else text

        result = {
            "name": clean_placeholder(name),
            "civility": clean_placeholder(civility),
            "addr": clean_placeholder(address),
            "project_address": clean_placeholder(address),
            "phone": clean_placeholder(phone),
            "email": clean_placeholder(email),
            "desc": clean_placeholder(description),
            "service": clean_placeholder(description),
            "odsNum": ods_num,
        }
        if description:
            result["service_lines"] = [
                line.strip().lstrip("•").strip().rstrip(";")
                for line in description.splitlines()
                if line.strip()
            ][:5]
        logger.info(
            "Recovered invoice metadata from %s: name=%s email=%s address=%s",
            filename, bool(result.get("name")), bool(result.get("email")), bool(result.get("addr")),
        )
        return result
    except Exception:
        logger.exception("Unable to recover project metadata from ODS Excel")
        return {}


def onedrive_projects():
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
    session.pop("selected_onedrive_project", None)
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
        selected = session.get("selected_onedrive_project") or {}
        if str(selected.get("choice_id") or "") == str(choice_id):
            if session.get("waiting_invoice_contract_amount"):
                return
            if float(session.get("price") or 0) > 0:
                base.show_invoice_options_multi(chat_id, uid)
            return
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
        recovered = recover_project_metadata_from_onedrive(folder)
        data = {
            **recovered,
            "project_folder": folder,
            "project_web_url": choice.get("web_url") or "",
            "project_created": True,
            "price": float(recovered.get("price") or 0),
        }

    data["pending_invoice"] = None
    data["waiting_invoice_percentage"] = False
    data["waiting_invoice_amount"] = False
    data["invoice_project_choices"] = session.get("invoice_project_choices") or {}
    data["selected_onedrive_project"] = {
        "choice_id": str(choice_id),
        "folder": folder,
        "web_url": choice.get("web_url") or "",
    }
    legacy.user_data[uid] = data
    legacy.save_user_data()

    if float(data.get("price") or 0) <= 0:
        data["waiting_invoice_contract_amount"] = True
        legacy.user_data[uid] = data
        legacy.save_user_data()
        client_note = ""
        if data.get("name"):
            client_note = f"\nClient détecté : {data['name']}"
        legacy.tg(
            chat_id,
            f"✅ Projet sélectionné : {folder}{client_note}\n\n"
            "💰 Quel est le montant total du contrat avant taxes?\n"
            "Exemple : 5500",
        )
        return

    base.show_invoice_options_multi(chat_id, uid)


_original_handle_update = legacy.handle_update


def handle_update_runtime(data):
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
