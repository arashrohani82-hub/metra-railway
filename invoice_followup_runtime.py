"""Prepare and send invoice reminders from the accounting mailbox."""
import logging
import os
import secrets
import sqlite3
import threading
import urllib.parse
from contextlib import closing
from datetime import timedelta

import app as legacy
import ods_runtime
import payment_receipt_runtime as receipts

log = logging.getLogger(__name__)
BUTTON = "📨 Suivi des factures"
PREFIX = "invrel:"
PAGE_SIZE = 12
STAGES = (
    ("1 · Rappel courtois", "Rappel de paiement"),
    ("2 · Demander une date de paiement", "Deuxième suivi de paiement"),
    ("3 · Relance ferme avec échéance", "Relance de paiement"),
    ("4 · Dernier rappel après trois relances", "Dernier rappel de paiement"),
)
SESSIONS = {}
SESSION_LOCKS = {}


def button(label, action):
    return {"text": label, "callback_data": PREFIX + action}


def show_projects(chat_id, state, page):
    for field in ("invoice_key", "stage_key", "preview"):
        state.pop(field, None)
    projects = state["projects"]
    start = page * PAGE_SIZE
    rows = [[button(ods_runtime._project_payment_label(item, compact=True, show_payment=False),
                    f"{state['key']}:project:{i}")]
            for i, item in enumerate(projects[start:start + PAGE_SIZE], start)]
    navigation = []
    if page:
        navigation.append(button("‹ Précédent", f"{state['key']}:page:{page - 1}"))
    if start + PAGE_SIZE < len(projects):
        navigation.append(button("Suivant ›", f"{state['key']}:page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    legacy.tg(chat_id, "📨 Suivi des factures\n\nChoisissez un projet."
              if projects else "Aucun projet non soldé dans le suivi.", rows)


def show_invoices(chat_id, state, index):
    folder = state["projects"][index]["name"]
    invoices = receipts.open_project_invoices(folder)
    key = secrets.token_hex(6)
    state.update(folder=folder, invoices=invoices, invoice_key=key)
    state.pop("stage_key", None)
    state.pop("preview", None)
    rows = [[button(f"{invoice['filename']} · {cad(invoice['remaining'])}", f"{key}:invoice:{i}")]
            for i, invoice in enumerate(invoices)]
    legacy.tg(chat_id, f"{folder}\n\nChoisissez une facture avec un solde à recevoir."
              if invoices else f"{folder}\n\nAucune facture avec un solde à recevoir.",
              rows + [[button("‹ Projets", f"{state['key']}:page:{index // PAGE_SIZE}")]])


def cad(value):
    return f"{receipts.money(value):,.2f}".replace(",", " ").replace(".", ",") + " $ CAD"


def build_letter(invoice, stage, deadline):
    title = STAGES[stage][1]
    reference = invoice["filename"].removesuffix(".pdf").removesuffix(".PDF").split("_", 1)[0]
    subject = f"{title} — facture {reference}"
    balance = cad(invoice["remaining"])
    opening = f"La facture {reference} présente un solde de {balance}."
    by = deadline.isoformat()
    paragraphs = (
        "Nous vous transmettons un rappel concernant cette facture. Pourriez-vous nous confirmer si le paiement est en cours de traitement?",
        "Nous revenons vers vous au sujet de cette facture. Merci de nous confirmer par écrit la date à laquelle le paiement sera effectué.",
        f"À la suite de nos précédents suivis, nous vous demandons de régler le solde au plus tard le {by}. Merci de nous confirmer par écrit la date du virement.",
        f"Malgré nos trois relances et vos engagements de paiement, nous n’avons toujours pas reçu le règlement. Nous vous demandons de régler le solde au plus tard le {by}. Merci de nous confirmer par écrit la date du virement.",
    )
    body = "\n\n".join((
        f"Bonjour {invoice['client']},", opening, paragraphs[stage],
        "Si le paiement a déjà été effectué, merci de nous transmettre la confirmation de paiement.",
        "Cordialement,\nService de comptabilité\nMetra Consultation Inc.",
    ))
    return subject, body


def open_dispatch():
    db = sqlite3.connect(os.path.join(legacy.DATA_DIR, "invoice_followup.sqlite3"))
    db.execute("""CREATE TABLE IF NOT EXISTS dispatch (
        id TEXT PRIMARY KEY, status TEXT NOT NULL, invoice TEXT NOT NULL,
        stage INTEGER NOT NULL, date TEXT NOT NULL
    )""")
    return db


def show_stages(chat_id, state, index):
    key = secrets.token_hex(6)
    invoice = state["invoices"][index]
    state.update(invoice=invoice, invoice_index=index, stage_key=key)
    state.pop("preview", None)
    rows = [[button(label, f"{key}:stage:{stage}")] for stage, (label, _) in enumerate(STAGES)]
    with closing(open_dispatch()) as db:
        recent = db.execute("SELECT stage, date FROM dispatch WHERE invoice = ? AND status = 'sent' ORDER BY rowid DESC LIMIT 1",
                            (invoice["filename"],)).fetchone()
    history = f"\nDernière relance via le bot : niveau {recent[0]}, le {recent[1]}." if recent else ""
    legacy.tg(chat_id, f"Facture : {invoice['filename']}\nClient : {invoice['client']}\n"
              f"Solde au registre : {cad(invoice['remaining'])}{history}\n\nChoisissez le niveau de relance. "
              "Utilisez le dernier rappel si trois relances ont déjà été faites et que le paiement promis n’a pas été reçu.", rows)


def show_preview(chat_id, state, stage, days=5):
    invoice = state["invoice"]
    deadline = receipts.today() + timedelta(days=days)
    subject, body = build_letter(invoice, stage, deadline)
    email = legacy.valid_client_email(invoice["email"])
    key = secrets.token_hex(12)
    state["preview"] = dict(key=key, invoice=invoice, folder=state["folder"],
                            subject=subject, body=body, email=email, deadline=deadline, stage=stage)
    rows = [[button("✉️ Confirmer et envoyer", f"{key}:send:0")]] if email else []
    if stage >= 2:
        rows.append([button(f"Délai {days} j", f"{key}:deadline:{days}") for days in (3, 5, 7)])
    rows.append([button("‹ Niveaux de relance", f"{state['stage_key']}:levels:0"),
                 button("❌ Annuler", f"{key}:cancel:0")])
    legacy.tg(chat_id, f"Destinataire : {email or 'courriel absent de la facture'}\n"
              f"Objet : {subject}\n\n{body}\n\n"
              "Avant de confirmer, vérifiez le destinataire et les paiements reçus hors du registre.", rows)


def send_preview(chat_id, preview):
    key = preview["key"]
    invoice = preview["invoice"]
    if not preview["email"]:
        raise ValueError("Courriel du client absent de la facture.")
    if preview["stage"] >= 2 and preview["deadline"] <= receipts.today():
        raise ValueError("Le délai du brouillon a expiré. Préparez une nouvelle relance.")
    confirmed_client = ods_runtime.confirmed_project_client(preview["folder"])
    if confirmed_client and legacy.normalize_client_name(invoice["client"]).casefold() != confirmed_client.casefold():
        raise ValueError("Le client indiqué sur la facture diffère de celui confirmé pour le projet.")
    projects = ods_runtime.projects_awaiting_settlement([{"name": preview["folder"]}])
    if not projects:
        raise ValueError("Ce projet est soldé ou fermé dans le suivi.")
    token = legacy.graph_access_token()
    sender = urllib.parse.quote(legacy.INVOICE_EMAIL_SENDER, safe="")
    payload = {
        "message": {
            "subject": preview["subject"],
            "body": {"contentType": "Text", "content": preview["body"]},
            "toRecipients": [{"emailAddress": {"address": preview["email"]}}],
            "ccRecipients": [{"emailAddress": {"address": legacy.INVOICE_CC_EMAIL}}],
        },
        "saveToSentItems": True,
    }
    with receipts.LOCK, closing(open_dispatch()) as db:
        existing = db.execute("SELECT status FROM dispatch WHERE id = ?", (key,)).fetchone()
        if existing:
            legacy.tg(chat_id, "✅ Cette relance a déjà été envoyée." if existing[0] == "sent" else
                      "⚠️ Envoi précédent incertain. Vérifiez les éléments envoyés de la boîte comptable.")
            return
        _, balance = receipts.payment_balance(invoice, receipts.invoice_records(invoice))
        if balance <= 0 or balance != receipts.money(invoice["remaining"]):
            raise ValueError("Le solde de la facture a changé. Rouvrez le projet pour actualiser la relance.")
        db.execute("INSERT INTO dispatch VALUES (?, 'pending', ?, ?, ?)",
                   (key, invoice["filename"], preview["stage"] + 1, receipts.today().isoformat()))
        db.commit()
        try:
            response = legacy.req.post(
                f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
                headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=45,
            )
        except legacy.req.RequestException:
            log.exception("Invoice reminder delivery outcome unknown")
            raise ValueError("Envoi non confirmé. Vérifiez les éléments envoyés de la boîte comptable.")
        if response.status_code != 202:
            if 400 <= response.status_code < 500 and response.status_code != 408:
                db.execute("DELETE FROM dispatch WHERE id = ?", (key,))
                db.commit()
                raise ValueError(f"Microsoft 365 a refusé l’envoi ({response.status_code}).")
            raise ValueError("Envoi non confirmé. Vérifiez les éléments envoyés de la boîte comptable.")
        db.execute("UPDATE dispatch SET status = 'sent' WHERE id = ?", (key,))
        db.commit()
    legacy.tg(chat_id, f"✅ Relance envoyée à {preview['email']}.")


def handle(update):
    callback = (update or {}).get("callback_query") or {}
    message = callback.get("message") or (update or {}).get("message") or {}
    action = str(callback.get("data") or "")
    text = str(message.get("text") or "").strip()
    opening = not callback and text == BUTTON
    if not opening and not action.startswith(PREFIX):
        return False
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    actor = ((callback if callback else message).get("from") or {}).get("id")
    if actor not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id, "⛔ Ce bot est privé.")
        return True
    if chat.get("type", "private") != "private":
        legacy.tg(chat_id, "Ouvrez le bot en privé pour consulter les factures.")
        return True
    if callback.get("id"):
        try:
            legacy.req.post(f"https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": callback["id"]}, timeout=3)
        except Exception:
            pass
    session_id = actor, chat_id
    with SESSION_LOCKS.setdefault(session_id, threading.Lock()):
        try:
            if opening:
                projects = ods_runtime.projects_awaiting_settlement(
                    ods_runtime.onedrive_projects(), include_financials=True)
                state = {"key": secrets.token_hex(6), "projects": projects}
                SESSIONS[session_id] = state
                show_projects(chat_id, state, 0)
                return True
            state = SESSIONS.get(session_id, {})
            key, operation, value = action[len(PREFIX):].split(":")
            index = int(value)
            preview = state.get("preview", {})
            if operation == "page" and key == state.get("key") and 0 <= index * PAGE_SIZE < len(state["projects"]):
                show_projects(chat_id, state, index)
            elif operation == "project" and key == state.get("key") and 0 <= index < len(state["projects"]):
                show_invoices(chat_id, state, index)
            elif operation == "invoice" and key == state.get("invoice_key") and 0 <= index < len(state["invoices"]):
                show_stages(chat_id, state, index)
            elif operation == "stage" and key == state.get("stage_key") and 0 <= index < len(STAGES):
                show_preview(chat_id, state, index)
            elif operation == "levels" and key == state.get("stage_key"):
                show_stages(chat_id, state, state["invoice_index"])
            elif operation == "deadline" and key == preview.get("key") and preview["stage"] >= 2 and index in (3, 5, 7):
                show_preview(chat_id, state, preview["stage"], days=index)
            elif operation == "send" and key == preview.get("key"):
                send_preview(chat_id, preview)
            elif operation == "cancel" and key == preview.get("key"):
                state.pop("preview", None)
                legacy.tg(chat_id, "Brouillon fermé.")
            else:
                legacy.tg(chat_id, f"Ce bouton a expiré. Rouvrez {BUTTON}.")
        except ValueError as exc:
            legacy.tg(chat_id, f"⚠️ {exc}")
        except Exception:
            log.exception("Invoice reminder workflow failed")
            legacy.tg(chat_id, f"❌ Suivi indisponible. Rouvrez {BUTTON} et réessayez.")
    return True


def install_menu():
    previous = legacy.main_menu

    def with_followup():
        menu = previous()
        rows = menu.get("keyboard", [])
        if not any(BUTTON == cell.get("text") for row in rows for cell in row):
            insert_at = next((i + 1 for i, row in enumerate(rows)
                              if any(cell.get("text") == "🧾 Facturation" for cell in row)), len(rows))
            rows.insert(insert_at, [{"text": BUTTON}])
        return menu

    legacy.main_menu = with_followup
