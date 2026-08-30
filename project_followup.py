import json
import os
import threading
from datetime import date, datetime


STATUS_LABELS = {
    "in_progress": "🟢 En cours",
    "waiting_client": "🟡 Attente client",
    "waiting_external": "🟠 Attente externe",
    "blocked": "🔴 Bloqué",
    "ready_invoice": "🧾 Prêt à facturer",
    "completed": "✅ Terminé",
    "cancelled": "⚫ Annulé",
}

BLOCKER_LABELS = {
    "none": "Aucun",
    "client": "Client",
    "municipality": "Municipalité / permis",
    "site": "Accès / relevé au chantier",
    "technical": "Décision technique",
    "payment": "Paiement",
}

NEXT_ACTION_LABELS = {
    "site_visit": "Visite / relevé",
    "calculations": "Calculs",
    "drawings": "Plans",
    "report": "Rapport",
    "client": "Contacter le client",
    "invoice": "Préparer la facture",
    "none": "À définir",
}

FINANCIAL_LABELS = {
    "deposit_pending": "Avance 25 % à facturer",
    "deposit_issued": "Avance 25 % facturée",
    "partial": "Facturation partielle",
    "ready": "Prêt pour prochaine facture",
    "fully_invoiced": "Entièrement facturé",
}


def iso_now(now=None):
    return (now or datetime.now()).replace(microsecond=0).isoformat()


def default_project(folder, web_url="", now=None):
    return {
        "folder": folder,
        "web_url": web_url or "",
        "status": "in_progress",
        "progress": 0,
        "blocker": "none",
        "next_action": "none",
        "financial": "deposit_pending",
        "due_date": "",
        "updated_at": iso_now(now),
    }


def normalize_project(record, folder="", web_url="", now=None):
    base = default_project(folder or str((record or {}).get("folder") or ""), web_url, now)
    base.update(record or {})
    if web_url:
        base["web_url"] = web_url
    if base.get("status") not in STATUS_LABELS:
        base["status"] = "in_progress"
    if base.get("blocker") not in BLOCKER_LABELS:
        base["blocker"] = "none"
    if base.get("next_action") not in NEXT_ACTION_LABELS:
        base["next_action"] = "none"
    if base.get("financial") not in FINANCIAL_LABELS:
        base["financial"] = "deposit_pending"
    try:
        base["progress"] = max(0, min(100, int(base.get("progress") or 0)))
    except (TypeError, ValueError):
        base["progress"] = 0
    return base


def parse_date(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def parse_datetime(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def project_flags(project, today=None, now=None, stale_days=7):
    today = today or date.today()
    now = now or datetime.now()
    due = parse_date(project.get("due_date"))
    updated = parse_datetime(project.get("updated_at"))
    due_in = (due - today).days if due else None
    stale_for = (now - updated).days if updated else stale_days
    return {
        "overdue": due_in is not None and due_in < 0,
        "due_soon": due_in is not None and 0 <= due_in <= 3,
        "due_in": due_in,
        "stale": stale_for >= stale_days,
        "stale_for": stale_for,
        "blocked": project.get("status") == "blocked" or project.get("blocker") not in (None, "", "none"),
    }


def is_open(project):
    return project.get("status") not in ("completed", "cancelled")


def needs_attention(project, today=None, now=None):
    flags = project_flags(project, today=today, now=now)
    return is_open(project) and any(flags[key] for key in ("overdue", "due_soon", "stale", "blocked"))


def due_text(project, today=None):
    due = parse_date(project.get("due_date"))
    if not due:
        return "Non fixée"
    delta = (due - (today or date.today())).days
    if delta < 0:
        return f"{due.isoformat()} — en retard de {abs(delta)} j"
    if delta == 0:
        return f"{due.isoformat()} — aujourd’hui"
    return f"{due.isoformat()} — dans {delta} j"


def update_project(project, now=None, **changes):
    updated = normalize_project(project, now=now)
    updated.update(changes)
    if updated.get("status") == "completed":
        updated["progress"] = 100
        updated["blocker"] = "none"
    updated["updated_at"] = iso_now(now)
    return normalize_project(updated, now=now)


def attention_reason(project, today=None, now=None):
    flags = project_flags(project, today=today, now=now)
    reasons = []
    if flags["overdue"]:
        reasons.append(f"échéance dépassée de {abs(flags['due_in'])} j")
    elif flags["due_soon"]:
        reasons.append("échéance aujourd’hui" if flags["due_in"] == 0 else f"échéance dans {flags['due_in']} j")
    if flags["blocked"]:
        reasons.append("bloqué: " + BLOCKER_LABELS.get(project.get("blocker"), "à vérifier"))
    if flags["stale"]:
        reasons.append(f"sans mise à jour depuis {flags['stale_for']} j")
    return ", ".join(reasons)


class ProjectStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError("invalid project store")
                payload.setdefault("projects", {})
                payload.setdefault("scheduler", {})
                return payload
            except (FileNotFoundError, json.JSONDecodeError, ValueError):
                return {"projects": {}, "scheduler": {}}

    def save(self, payload):
        with self.lock:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self.path)

    def upsert(self, folder, web_url="", now=None, **changes):
        with self.lock:
            payload = self.load()
            current = normalize_project(payload["projects"].get(folder), folder, web_url, now)
            if changes:
                current = update_project(current, now=now, **changes)
            payload["projects"][folder] = current
            self.save(payload)
            return current

    def set_scheduler_value(self, key, value):
        with self.lock:
            payload = self.load()
            payload["scheduler"][key] = value
            self.save(payload)
