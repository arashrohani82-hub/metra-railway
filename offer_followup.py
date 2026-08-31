import json
import os
import threading
from datetime import date, datetime


OPEN_STATUSES = {"In process", "Hold"}


FOLLOWUP_EMAILS = {
    3: (
        "Je me permets de faire un suivi concernant notre offre de service {reference}. "
        "Avez-vous eu l’occasion d’en prendre connaissance? Nous demeurons disponibles pour répondre à vos questions."
    ),
    7: (
        "Nous souhaitons faire un deuxième suivi concernant notre offre de service {reference}. "
        "N’hésitez pas à nous indiquer si vous souhaitez obtenir des précisions ou discuter de certains éléments du mandat."
    ),
    10: (
        "Nous revenons vers vous concernant notre offre de service {reference}. "
        "Pourriez-vous nous confirmer si le projet est toujours d’actualité et si vous souhaitez poursuivre avec les prochaines étapes?"
    ),
    15: (
        "Nous effectuons un dernier suivi concernant notre offre de service {reference}. "
        "Sans retour de votre part, nous considérerons la demande comme étant en suspens et fermerons le dossier pour le moment. "
        "Nous pourrons naturellement le rouvrir si vous souhaitez poursuivre ultérieurement."
    ),
}


def build_followup_email(offer, followup_day):
    day = int(followup_day)
    if day not in FOLLOWUP_EMAILS:
        raise ValueError("unsupported follow-up day")
    reference = str(offer.get("reference") or "votre projet").strip()
    contact = str(offer.get("contact") or "").strip()
    greeting = f"Bonjour {contact}," if contact else "Bonjour,"
    subject = f"Suivi – Offre de service {reference}"
    body = (
        f"{greeting}\n\n"
        f"{FOLLOWUP_EMAILS[day].format(reference=reference)}\n\n"
        "Cordialement,\n\n"
        "Arash Rohani, ing., P.Eng.\n"
        "Président – Ingénieur en structure\n"
        "Metra Consultation Inc.\n"
        "arash.rohani@metrastructure.ca | (438) 867-4131"
    )
    return subject, body


def recommended_followup_day(age_days):
    days = max(0, int(age_days or 0))
    if days >= 15:
        return 15
    if days >= 10:
        return 10
    if days >= 7:
        return 7
    return 3


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def followup_stage(sent_at, today=None):
    sent = parse_date(sent_at)
    if not sent:
        return {"days": 0, "stage": 0, "label": "Date inconnue", "urgent": False}
    days = max(0, ((today or date.today()) - sent).days)
    if days >= 90:
        return {"days": days, "stage": 3, "label": "Troisième relance mensuelle (+90 j)", "urgent": True}
    if days >= 60:
        return {"days": days, "stage": 2, "label": "Deuxième relance mensuelle (+60 j)", "urgent": False}
    if days >= 30:
        return {"days": days, "stage": 1, "label": "Première relance mensuelle (+30 j)", "urgent": False}
    return {"days": days, "stage": 0, "label": "Pas encore à relancer", "urgent": False}


def normalized_status(value):
    raw = str(value or "In process").strip().lower()
    aliases = {
        "in process": "In process", "in progress": "In process",
        "hold": "Hold", "on hold": "Hold",
        "accept": "Accept", "accepted": "Accept", "accepté": "Accept",
        "refused": "Refused", "rejected": "Refused",
        "closed": "Closed", "close": "Closed",
    }
    return aliases.get(raw, str(value or "In process").strip().title())


def is_open_offer(offer):
    return normalized_status(offer.get("status")) in OPEN_STATUSES


def mark_followed(state=None, today=None):
    today = today or date.today()
    current = dict(state or {})
    current["followup_count"] = int(current.get("followup_count") or 0) + 1
    current["last_followup_at"] = today.isoformat()
    return current


class FollowupStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError
                payload.setdefault("offers", {})
                payload.setdefault("scheduler", {})
                return payload
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                return {"offers": {}, "scheduler": {}}

    def save(self, payload):
        with self.lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)

    def mark_followed(self, reference, today=None, email_day=None):
        with self.lock:
            payload = self.load()
            state = mark_followed(payload["offers"].get(reference), today)
            if email_day is not None:
                state["last_email_stage"] = int(email_day)
            payload["offers"][reference] = state
            self.save(payload)
            return state

    def scheduler_value(self, key, value=None):
        with self.lock:
            payload = self.load()
            if value is None:
                return payload["scheduler"].get(key)
            payload["scheduler"][key] = value
            self.save(payload)
            return value
