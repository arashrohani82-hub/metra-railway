import logging
import os
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import menu_guard_runtime as guarded
from project_followup import (
    BLOCKER_LABELS,
    FINANCIAL_LABELS,
    NEXT_ACTION_LABELS,
    STATUS_LABELS,
    ProjectStore,
    attention_reason,
    due_text,
    is_open,
    needs_attention,
)


app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)

STORE = ProjectStore(os.path.join(legacy.DATA_DIR, "project_followups.json"))
TIMEZONE_NAME = os.environ.get("PROJECT_FOLLOWUP_TIMEZONE", "America/Toronto")
WEEKDAY = int(os.environ.get("PROJECT_FOLLOWUP_WEEKDAY", "0"))
FOLLOWUP_HOUR = int(os.environ.get("PROJECT_FOLLOWUP_HOUR", "9"))
SCHEDULER_ENABLED = os.environ.get("PROJECT_FOLLOWUP_SCHEDULER_ENABLED", "1") != "0"
_base_main_menu = guarded.final_main_menu


def local_now():
    try:
        return datetime.now(ZoneInfo(TIMEZONE_NAME))
    except Exception:
        return datetime.now(ZoneInfo("UTC"))


def followup_main_menu():
    menu = _base_main_menu()
    keyboard = list(menu.get("keyboard") or [])
    insert_at = 4 if len(keyboard) >= 4 else len(keyboard)
    keyboard.insert(insert_at, [{"text": "🔄 Suivi projets"}])
    menu["keyboard"] = keyboard
    return menu


# Replace the menu function looked up by the guard at runtime as well as the
# legacy function used by older flows.
guarded.final_main_menu = followup_main_menu
guarded.MAIN_MENU_COMMANDS.add("🔄 Suivi projets")
legacy.main_menu = followup_main_menu


def _ack(callback):
    try:
        requests.post(
            f"https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback.get("id")},
            timeout=3,
        )
    except Exception:
        pass


def _onedrive_project_items():
    config = legacy.microsoft_email_config()
    token = legacy.graph_access_token()
    owner = config["EMAIL_SENDER"]
    current_year = local_now().year
    projects = []
    for year in (current_year, current_year - 1):
        root = f"Metra Structure Inc/Projects/{year}"
        try:
            items = legacy.list_onedrive_children(token, owner, root)
        except Exception as exc:
            logger.warning("Project follow-up could not read %s: %s", root, exc)
            continue
        for item in items:
            folder = str(item.get("name") or "").strip()
            if item.get("folder") is not None and folder.upper().startswith(f"P{str(year)[-2:]}-"):
                projects.append({
                    "folder": folder,
                    "web_url": str(item.get("webUrl") or ""),
                    "year": year,
                })
    projects.sort(key=lambda item: item["folder"], reverse=True)
    return projects


def _sync_projects_from_onedrive():
    items = _onedrive_project_items()
    records = {}
    for item in items:
        record = STORE.upsert(item["folder"], item.get("web_url") or "")
        records[item["folder"]] = record
    return items, records


def _session(uid):
    return legacy.user_data.setdefault(str(uid), {})


def _save_session(uid, session):
    legacy.user_data[str(uid)] = session
    legacy.save_user_data()


def show_open_projects(chat_id, uid, intro=""):
    try:
        items, records = _sync_projects_from_onedrive()
    except Exception as exc:
        logger.exception("Project follow-up list failed")
        legacy.tg(chat_id, f"❌ Lecture des projets OneDrive impossible : {exc}")
        return

    open_items = [item for item in items if is_open(records[item["folder"]])]
    session = _session(uid)
    choices = {}
    rows = []
    now = local_now()
    for index, item in enumerate(open_items[:40], start=1):
        folder = item["folder"]
        project = records[folder]
        choices[str(index)] = folder
        warning = "⚠️ " if needs_attention(project, today=now.date(), now=now.replace(tzinfo=None)) else ""
        label = f"{warning}{project.get('progress', 0)}% · {folder}"
        rows.append([{"text": label[:62], "callback_data": f"pf_project:{index}"}])
    session["followup_choices"] = choices
    session.pop("followup_selected", None)
    _save_session(uid, session)

    if not rows:
        legacy.tg(chat_id, "✅ Aucun projet ouvert dans les deux dernières années.")
        return
    heading = "🔄 Suivi des projets ouverts"
    if intro:
        heading = intro + "\n\n" + heading
    legacy.tg(
        chat_id,
        f"{heading}\n\n{len(open_items)} projet(s) ouvert(s). Choisissez un projet :",
        rows,
    )


def _selected_project(uid):
    session = _session(uid)
    folder = str(session.get("followup_selected") or "")
    if not folder:
        return "", None
    return folder, STORE.load().get("projects", {}).get(folder)


def _project_text(project):
    status = STATUS_LABELS.get(project.get("status"), project.get("status"))
    blocker = BLOCKER_LABELS.get(project.get("blocker"), project.get("blocker"))
    action = NEXT_ACTION_LABELS.get(project.get("next_action"), project.get("next_action"))
    financial = FINANCIAL_LABELS.get(project.get("financial"), project.get("financial"))
    updated = str(project.get("updated_at") or "")[:16].replace("T", " ")
    return (
        f"🔄 {project.get('folder')}\n\n"
        f"Statut : {status}\n"
        f"Avancement : {project.get('progress', 0)} %\n"
        f"Prochaine action : {action}\n"
        f"Blocage : {blocker}\n"
        f"Échéance : {due_text(project, local_now().date())}\n"
        f"Finances : {financial}\n"
        f"Dernière mise à jour : {updated or '—'}"
    )


def show_project(chat_id, uid):
    folder, project = _selected_project(uid)
    if not folder or not project:
        legacy.tg(chat_id, "❌ Projet introuvable. Ouvrez de nouveau Suivi projets.")
        return
    buttons = [
        [
            {"text": "📊 Avancement", "callback_data": "pf_menu:progress"},
            {"text": "🚦 Statut", "callback_data": "pf_menu:status"},
        ],
        [
            {"text": "➡️ Action", "callback_data": "pf_menu:action"},
            {"text": "⛔ Blocage", "callback_data": "pf_menu:blocker"},
        ],
        [
            {"text": "📅 Échéance", "callback_data": "pf_menu:due"},
            {"text": "💰 Finances", "callback_data": "pf_menu:financial"},
        ],
        [{"text": "📂 Ouvrir OneDrive", "url": project.get("web_url") or "https://www.microsoft365.com"}],
        [{"text": "⬅️ Tous les projets", "callback_data": "pf_back"}],
    ]
    legacy.tg(chat_id, _project_text(project), buttons)


def _show_choice_menu(chat_id, kind):
    menus = {
        "progress": ("📊 Avancement", [
            [("0 %", "0"), ("25 %", "25"), ("50 %", "50")],
            [("75 %", "75"), ("90 %", "90"), ("100 %", "100")],
        ]),
        "status": ("🚦 Statut", [
            [("🟢 En cours", "in_progress"), ("🟡 Client", "waiting_client")],
            [("🟠 Externe", "waiting_external"), ("🔴 Bloqué", "blocked")],
            [("🧾 À facturer", "ready_invoice"), ("✅ Terminé", "completed")],
        ]),
        "action": ("➡️ Prochaine action", [
            [("Visite", "site_visit"), ("Calculs", "calculations")],
            [("Plans", "drawings"), ("Rapport", "report")],
            [("Client", "client"), ("Facture", "invoice")],
        ]),
        "blocker": ("⛔ Blocage", [
            [("✅ Aucun", "none"), ("Client", "client")],
            [("Municipalité", "municipality"), ("Chantier", "site")],
            [("Technique", "technical"), ("Paiement", "payment")],
        ]),
        "financial": ("💰 Situation financière", [
            [("Avance à faire", "deposit_pending"), ("Avance faite", "deposit_issued")],
            [("Partielle", "partial"), ("À facturer", "ready")],
            [("100 % facturé", "fully_invoiced")],
        ]),
        "due": ("📅 Échéance", [
            [("+3 jours", "3"), ("+7 jours", "7"), ("+14 jours", "14")],
            [("+30 jours", "30"), ("Sans date", "clear")],
        ]),
    }
    title, rows = menus[kind]
    keyboard = [[{"text": label, "callback_data": f"pf_set:{kind}:{value}"} for label, value in row] for row in rows]
    keyboard.append([{"text": "⬅️ Retour", "callback_data": "pf_detail"}])
    legacy.tg(chat_id, title + " — choisissez une option :", keyboard)


def _apply_choice(chat_id, uid, kind, value):
    folder, project = _selected_project(uid)
    if not folder or not project:
        legacy.tg(chat_id, "❌ Projet introuvable.")
        return
    changes = {}
    if kind == "progress":
        changes["progress"] = int(value)
    elif kind == "status" and value in STATUS_LABELS:
        changes["status"] = value
    elif kind == "action" and value in NEXT_ACTION_LABELS:
        changes["next_action"] = value
    elif kind == "blocker" and value in BLOCKER_LABELS:
        changes["blocker"] = value
        if value != "none":
            changes["status"] = "blocked"
        elif project.get("status") == "blocked":
            changes["status"] = "in_progress"
    elif kind == "financial" and value in FINANCIAL_LABELS:
        changes["financial"] = value
        if value == "ready":
            changes["status"] = "ready_invoice"
    elif kind == "due":
        changes["due_date"] = "" if value == "clear" else (local_now().date() + timedelta(days=int(value))).isoformat()
    if not changes:
        legacy.tg(chat_id, "❌ Choix non valide.")
        return
    STORE.upsert(folder, project.get("web_url") or "", **changes)
    legacy.tg(chat_id, "✅ Suivi mis à jour.")
    show_project(chat_id, uid)


def _attention_projects():
    try:
        _sync_projects_from_onedrive()
    except Exception:
        logger.exception("Scheduled project reconciliation failed")
    now = local_now()
    records = STORE.load().get("projects", {})
    return [
        project for project in records.values()
        if needs_attention(project, today=now.date(), now=now.replace(tzinfo=None))
    ]


def send_attention_digest(chat_id):
    projects = _attention_projects()
    if not projects:
        return False
    lines = ["⚠️ Points à suivre aujourd’hui", ""]
    for project in projects[:20]:
        lines.append(f"• {project.get('folder')}: {attention_reason(project, local_now().date(), local_now().replace(tzinfo=None))}")
    if len(projects) > 20:
        lines.append(f"• … et {len(projects) - 20} autre(s)")
    lines.extend(["", "Ouvrez « 🔄 Suivi projets » pour mettre à jour."])
    legacy.tg(chat_id, "\n".join(lines), reply_markup=followup_main_menu())
    return True


def _scheduler_loop():
    # Give the web process time to finish booting and webhook registration.
    threading.Event().wait(30)
    while True:
        try:
            now = local_now()
            payload = STORE.load()
            scheduler = payload.get("scheduler", {})
            today = now.date().isoformat()
            if now.hour == FOLLOWUP_HOUR:
                if scheduler.get("last_attention") != today:
                    for chat_id in sorted(legacy.ALLOWED_USERS):
                        send_attention_digest(chat_id)
                    STORE.set_scheduler_value("last_attention", today)
                if now.weekday() == WEEKDAY and scheduler.get("last_weekly") != today:
                    for chat_id in sorted(legacy.ALLOWED_USERS):
                        show_open_projects(chat_id, str(chat_id), "📅 Revue hebdomadaire")
                    STORE.set_scheduler_value("last_weekly", today)
        except Exception:
            logger.exception("Project follow-up scheduler failed")
        threading.Event().wait(900)


_previous_handle_update = legacy.handle_update


def handle_update_project_followup(data):
    msg = data.get("message") or {}
    callback = data.get("callback_query") or {}
    actor_id = (callback.get("from") or msg.get("from") or {}).get("id")
    chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id") if callback else (msg.get("chat") or {}).get("id")

    if msg and str(msg.get("text") or "").strip() == "🔄 Suivi projets":
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, "⛔ Ce bot est privé.")
            return
        legacy.executor.submit(show_open_projects, chat_id, str(actor_id))
        return

    cdata = str(callback.get("data") or "")
    if cdata.startswith("pf_"):
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, "⛔ Ce bot est privé.")
            return
        _ack(callback)
        uid = str(actor_id)
        if cdata.startswith("pf_project:"):
            choice = cdata.split(":", 1)[1]
            session = _session(uid)
            folder = (session.get("followup_choices") or {}).get(choice)
            if not folder:
                legacy.tg(chat_id, "❌ Liste expirée. Ouvrez de nouveau Suivi projets.")
                return
            session["followup_selected"] = folder
            _save_session(uid, session)
            show_project(chat_id, uid)
        elif cdata.startswith("pf_menu:"):
            _show_choice_menu(chat_id, cdata.split(":", 1)[1])
        elif cdata.startswith("pf_set:"):
            _, kind, value = cdata.split(":", 2)
            _apply_choice(chat_id, uid, kind, value)
        elif cdata == "pf_detail":
            show_project(chat_id, uid)
        elif cdata == "pf_back":
            legacy.executor.submit(show_open_projects, chat_id, uid)
        return

    return _previous_handle_update(data)


legacy.handle_update = handle_update_project_followup
logger.info("PROJECT FOLLOW-UP RUNTIME ACTIVE")

if SCHEDULER_ENABLED and legacy.ALLOWED_USERS:
    threading.Thread(target=_scheduler_loop, name="project-followup", daemon=True).start()
