"""Read-only invoice follow-up entry point; never sends customer messages.

Uses the existing OneDrive project structure and Telegram authorization.
No invoice numbering, invoice generation, or payment status is modified.
"""
import logging
import app as legacy
import ods_runtime

log = logging.getLogger(__name__)
BUTTON = "📨 Suivi des factures"


def show(chat_id):
    try:
        projects = ods_runtime.onedrive_projects()
    except Exception:
        log.exception("Invoice follow-up project listing failed")
        legacy.tg(chat_id, "❌ Impossible de consulter OneDrive. Réessayez plus tard.")
        return
    if not projects:
        legacy.tg(chat_id, "📨 Suivi des factures\nAucun projet trouvé.")
        return
    lines = ["📨 Suivi des factures — consultation", "",
             "Projets récents (lecture seule) :"]
    lines.extend("• " + str(item.get("name") or "")[:75] for item in projects[:20])
    lines.extend(["", "⚠️ Statuts de paiement non vérifiés.",
                  "Aucune relance client ne sera envoyée sans validation."])
    legacy.tg(chat_id, "\n".join(lines))


def handle(update):
    message = (update or {}).get("message") or {}
    if str(message.get("text") or "").strip() != BUTTON:
        return False
    chat_id = (message.get("chat") or {}).get("id")
    actor = (message.get("from") or {}).get("id")
    if actor not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id, "⛔ Ce bot est privé.")
        return True
    show(chat_id)
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
