import io
import logging
import os
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import openpyxl
import requests

import menu_guard_runtime as guarded
from offer_followup import FollowupStore, followup_stage, is_due, is_open_offer, normalized_status


app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)

STORE = FollowupStore(os.path.join(legacy.DATA_DIR, "offer_followups.json"))
TIMEZONE_NAME = os.environ.get("OFFER_FOLLOWUP_TIMEZONE", "America/Toronto")
FOLLOWUP_HOUR = int(os.environ.get("OFFER_FOLLOWUP_HOUR", "9"))
SCHEDULER_ENABLED = os.environ.get("OFFER_FOLLOWUP_SCHEDULER_ENABLED", "1") != "0"
_base_main_menu = guarded.final_main_menu


def local_now():
    try:
        return datetime.now(ZoneInfo(TIMEZONE_NAME))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def followup_main_menu():
    menu = _base_main_menu()
    keyboard = list(menu.get("keyboard") or [])
    keyboard.insert(4 if len(keyboard) >= 4 else len(keyboard), [{"text": "📬 Suivi offres"}])
    menu["keyboard"] = keyboard
    return menu


guarded.final_main_menu = followup_main_menu
guarded.MAIN_MENU_COMMANDS.add("📬 Suivi offres")
legacy.main_menu = followup_main_menu


def _ack(callback):
    try:
        requests.post(
            f"https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback.get("id")}, timeout=3,
        )
    except Exception:
        pass


def _reference(value):
    text = str(value or "").strip()
    match = re.search(r"ODS\d{2}-\d{3}(?:-[A-Z]{3})?", text, re.I)
    return match.group(0).upper() if match else text[:80]


def _amount(value):
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or "0").replace("$", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def load_open_offers():
    config = legacy.microsoft_email_config()
    token = legacy.graph_access_token()
    content = legacy.download_onedrive_path(token, config["EMAIL_SENDER"], legacy.ODS_LIST_PATH)
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    offers = []
    for ws in workbook.worksheets:
        if not str(ws.title).lower().startswith("data "):
            continue
        headers = {str(cell.value or "").strip(): cell.column for cell in ws[1] if cell.value is not None}
        required = ("Description", "Date", "Status", "Price($)")
        if any(name not in headers for name in required):
            continue
        for row in range(2, ws.max_row + 1):
            description = str(ws.cell(row, headers["Description"]).value or "").strip()
            if not description:
                continue
            raw_date = ws.cell(row, headers["Date"]).value
            offer = {
                "reference": _reference(description),
                "description": description,
                "date": raw_date.isoformat() if hasattr(raw_date, "isoformat") else str(raw_date or ""),
                "status": normalized_status(ws.cell(row, headers["Status"]).value),
                "price": _amount(ws.cell(row, headers["Price($)"]).value),
                "contact": str(ws.cell(row, headers.get("Contact", 0)).value or "").strip() if headers.get("Contact") else "",
                "email": str(ws.cell(row, headers.get("Email", 0)).value or "").strip() if headers.get("Email") else "",
                "source": str(ws.cell(row, headers.get("Source", 0)).value or "").strip() if headers.get("Source") else "",
                "sheet": ws.title,
                "row": row,
            }
            if is_open_offer(offer):
                offers.append(offer)
    offers.sort(key=lambda item: (followup_stage(item["date"], local_now().date())["days"], item["reference"]), reverse=True)
    return offers


def update_list_status(reference, status):
    if status not in {"Hold", "Refused", "Closed", "In process"}:
        raise ValueError("statut non valide")
    with legacy.ods_list_lock:
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        owner = config["EMAIL_SENDER"]
        content = legacy.download_onedrive_path(token, owner, legacy.ODS_LIST_PATH)
        workbook = openpyxl.load_workbook(io.BytesIO(content))
        found = False
        for ws in workbook.worksheets:
            headers = {str(cell.value or "").strip(): cell.column for cell in ws[1] if cell.value is not None}
            if "Description" not in headers or "Status" not in headers:
                continue
            for row in range(2, ws.max_row + 1):
                description = str(ws.cell(row, headers["Description"]).value or "")
                if reference.upper() in description.upper():
                    ws.cell(row, headers["Status"]).value = status
                    found = True
                    break
            if found:
                break
        if not found:
            raise RuntimeError("offre introuvable dans List.xlsx")
        output = io.BytesIO()
        workbook.save(output)
        legacy.upload_onedrive_path(
            token, owner, legacy.ODS_LIST_PATH, output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _session(uid):
    return legacy.user_data.setdefault(str(uid), {})


def _save_session(uid, session):
    legacy.user_data[str(uid)] = session
    legacy.save_user_data()


def show_open_offers(chat_id, uid, due_only=False, intro=""):
    try:
        offers = load_open_offers()
    except Exception as exc:
        logger.exception("Open-offer follow-up list failed")
        legacy.tg(chat_id, f"❌ Lecture de List.xlsx impossible : {exc}")
        return
    states = STORE.load().get("offers", {})
    if due_only:
        offers = [offer for offer in offers if is_due(offer, states.get(offer["reference"]), local_now().date())]
    session = _session(uid)
    choices = {}
    rows = []
    for index, offer in enumerate(offers[:40], start=1):
        choices[str(index)] = offer
        stage = followup_stage(offer["date"], local_now().date())
        warning = "🔴 " if stage["urgent"] else "🟠 " if stage["stage"] >= 2 else "🟡 " if stage["stage"] == 1 else "⚪ "
        label = f"{warning}{stage['days']}j · {offer['reference']} · {offer['contact'] or 'Client'}"
        rows.append([{"text": label[:62], "callback_data": f"of_pick:{index}"}])
    session["offer_followup_choices"] = choices
    session.pop("offer_followup_selected", None)
    _save_session(uid, session)
    if not rows:
        message = "✅ Aucune relance due aujourd’hui." if due_only else "✅ Aucune offre ouverte dans List.xlsx."
        legacy.tg(chat_id, message, reply_markup=followup_main_menu())
        return
    title = "📬 Relances dues" if due_only else "📬 Suivi des offres ouvertes"
    if intro:
        title = intro + "\n\n" + title
    legacy.tg(chat_id, f"{title}\n\n{len(offers)} offre(s). Choisissez une offre :", rows)


def _selected(uid):
    session = _session(uid)
    return session.get("offer_followup_selected")


def _offer_text(offer, state):
    stage = followup_stage(offer.get("date"), local_now().date())
    sent = offer.get("date")
    sent_text = sent.strftime("%Y-%m-%d") if hasattr(sent, "strftime") else str(sent or "—")[:10]
    last = str(state.get("last_followup_at") or "Jamais")
    next_on = str(state.get("next_followup_on") or "Dès maintenant" if stage["stage"] else "À partir de J+3")
    return (
        f"📬 {offer['reference']}\n\n"
        f"Client : {offer.get('contact') or '—'}\n"
        f"Courriel : {offer.get('email') or '—'}\n"
        f"Montant : {offer.get('price', 0):,.0f} $\n"
        f"Envoyée : {sent_text} ({stage['days']} jours)\n"
        f"Statut : {offer.get('status')}\n"
        f"Étape : {stage['label']}\n"
        f"Relances enregistrées : {state.get('followup_count', 0)}\n"
        f"Dernière relance : {last}\n"
        f"Prochaine relance interne : {next_on}"
    )


def show_offer(chat_id, uid):
    offer = _selected(uid)
    if not offer:
        legacy.tg(chat_id, "❌ Offre introuvable. Ouvrez de nouveau Suivi offres.")
        return
    state = STORE.load().get("offers", {}).get(offer["reference"], {})
    buttons = [
        [{"text": "✅ Relance effectuée", "callback_data": "of_mark"}],
        [
            {"text": "⏸ Hold", "callback_data": "of_status:Hold"},
            {"text": "🔄 In process", "callback_data": "of_status:In process"},
        ],
        [
            {"text": "❌ Refused", "callback_data": "of_status:Refused"},
            {"text": "🔒 Closed", "callback_data": "of_status:Closed"},
        ],
        [{"text": "📁 Acceptée → projet", "callback_data": "of_convert"}],
        [{"text": "⬅️ Toutes les offres", "callback_data": "of_back"}],
    ]
    legacy.tg(chat_id, _offer_text(offer, state), buttons)


def _history_reference(uid, reference):
    for ref, record in (legacy.offers_history.get(str(uid), {}) or {}).items():
        data = (record or {}).get("data") or {}
        if reference.upper() in str(ref).upper() or reference.upper() in str(data.get("odsNum") or "").upper():
            return ref
    return ""


def _scheduler_loop():
    threading.Event().wait(30)
    while True:
        try:
            now = local_now()
            today = now.date().isoformat()
            if now.hour == FOLLOWUP_HOUR:
                if now.day == 1 and STORE.scheduler_value("last_monthly") != today:
                    for chat_id in sorted(legacy.ALLOWED_USERS):
                        show_open_offers(chat_id, str(chat_id), intro="📅 Revue mensuelle")
                    STORE.scheduler_value("last_monthly", today)
        except Exception:
            logger.exception("Offer follow-up scheduler failed")
        threading.Event().wait(900)


_previous_handle_update = legacy.handle_update


def handle_update_offer_followup(data):
    msg = data.get("message") or {}
    callback = data.get("callback_query") or {}
    actor_id = (callback.get("from") or msg.get("from") or {}).get("id")
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id") if callback else (msg.get("chat") or {}).get("id")
    if msg and str(msg.get("text") or "").strip() == "📬 Suivi offres":
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, "⛔ Ce bot est privé.")
            return
        legacy.executor.submit(show_open_offers, chat_id, str(actor_id))
        return
    cdata = str(callback.get("data") or "")
    if cdata.startswith("of_"):
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, "⛔ Ce bot est privé.")
            return
        _ack(callback)
        uid = str(actor_id)
        if cdata.startswith("of_pick:"):
            choice = cdata.split(":", 1)[1]
            session = _session(uid)
            offer = (session.get("offer_followup_choices") or {}).get(choice)
            if not offer:
                legacy.tg(chat_id, "❌ Liste expirée. Ouvrez de nouveau Suivi offres.")
                return
            session["offer_followup_selected"] = offer
            _save_session(uid, session)
            show_offer(chat_id, uid)
        elif cdata == "of_mark":
            offer = _selected(uid)
            if not offer:
                legacy.tg(chat_id, "❌ Offre introuvable.")
                return
            STORE.mark_followed(offer["reference"], local_now().date())
            legacy.tg(chat_id, "✅ Relance enregistrée. Prochain rappel interne dans 30 jours.")
            show_offer(chat_id, uid)
        elif cdata.startswith("of_status:"):
            offer = _selected(uid)
            status = cdata.split(":", 1)[1]
            if not offer:
                legacy.tg(chat_id, "❌ Offre introuvable.")
                return
            try:
                update_list_status(offer["reference"], status)
                offer["status"] = status
                session = _session(uid)
                session["offer_followup_selected"] = offer
                _save_session(uid, session)
                legacy.tg(chat_id, f"✅ List.xlsx mis à jour : {status}")
                show_offer(chat_id, uid)
            except Exception as exc:
                legacy.tg(chat_id, f"❌ Mise à jour impossible : {exc}")
        elif cdata == "of_convert":
            offer = _selected(uid)
            ref = _history_reference(uid, offer["reference"] if offer else "")
            if not ref:
                legacy.tg(chat_id, "⚠️ Fichier de session introuvable. Utilisez « Convertir une offre en projet » pour rechercher cette ODS.")
                return
            legacy.show_offer_conversion_confirmation(chat_id, uid, ref)
        elif cdata == "of_back":
            legacy.executor.submit(show_open_offers, chat_id, uid)
        return
    return _previous_handle_update(data)


legacy.handle_update = handle_update_offer_followup
logger.info("OPEN OFFER FOLLOW-UP RUNTIME ACTIVE")

if SCHEDULER_ENABLED and legacy.ALLOWED_USERS:
    threading.Thread(target=_scheduler_loop, name="offer-followup", daemon=True).start()
