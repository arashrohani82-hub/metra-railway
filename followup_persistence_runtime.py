import json
import logging
import os
import threading
from datetime import date

import offer_followup_runtime as guarded

app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)

_LOCAL_STORE = guarded.STORE
_FOLLOWUP_JSON_PATH = os.environ.get(
    "OFFER_FOLLOWUP_STORE_PATH",
    os.path.join(os.path.dirname(legacy.ODS_LIST_PATH), "offer_followups.json").replace("\\", "/"),
).strip("/")


class OneDriveFollowupStore:
    """Follow-up state with OneDrive as the durable source of truth.

    Railway's local filesystem can be replaced during deploys.  Keeping this
    small JSON beside List.xlsx makes follow-up counts/history survive restarts
    and deployments.  The existing local store remains a fallback if Graph is
    temporarily unavailable.
    """

    def __init__(self, local_store):
        self.local_store = local_store
        self.lock = threading.RLock()

    @staticmethod
    def _blank():
        return {"offers": {}, "scheduler": {}}

    @staticmethod
    def _normalize(payload):
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("offers", {})
        payload.setdefault("scheduler", {})
        if not isinstance(payload["offers"], dict):
            payload["offers"] = {}
        if not isinstance(payload["scheduler"], dict):
            payload["scheduler"] = {}
        return payload

    def _cloud_read(self):
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        owner = config["EMAIL_SENDER"]
        raw = legacy.download_onedrive_path(token, owner, _FOLLOWUP_JSON_PATH)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return self._normalize(json.loads(raw))

    def _cloud_write(self, payload):
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        owner = config["EMAIL_SENDER"]
        body = json.dumps(self._normalize(payload), ensure_ascii=False, indent=2).encode("utf-8")
        legacy.upload_onedrive_path(
            token,
            owner,
            _FOLLOWUP_JSON_PATH,
            body,
            "application/json",
        )

    def load(self):
        with self.lock:
            try:
                cloud = self._cloud_read()
                # Keep a warm local cache for Graph outages.
                try:
                    self.local_store.save(cloud)
                except Exception:
                    pass
                return cloud
            except Exception as exc:
                logger.warning("Follow-up cloud read unavailable, using local fallback: %s", exc)
                try:
                    return self._normalize(self.local_store.load())
                except Exception:
                    return self._blank()

    def save(self, payload):
        with self.lock:
            payload = self._normalize(payload)
            # Always keep local cache first, then durable OneDrive copy.
            self.local_store.save(payload)
            try:
                self._cloud_write(payload)
            except Exception:
                logger.exception("Follow-up cloud write failed")
                raise

    def mark_followed(self, reference, today=None, email_day=None):
        with self.lock:
            payload = self.load()
            ref = str(reference or "").strip().upper()
            state = dict(payload["offers"].get(ref) or {})
            when = today or date.today()
            when_text = when.isoformat() if hasattr(when, "isoformat") else str(when)

            history = list(state.get("history") or [])
            stage = int(email_day) if email_day is not None else None
            history.append({
                "date": when_text,
                "stage": stage,
                "type": "email" if stage is not None else "manual",
            })

            state["followup_count"] = len(history)
            state["last_followup_at"] = when_text
            state["history"] = history
            if stage is not None:
                state["last_email_stage"] = stage

            payload["offers"][ref] = state
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


STORE = OneDriveFollowupStore(_LOCAL_STORE)
guarded.STORE = STORE

_original_offer_text = guarded._offer_text


def _offer_text_with_history(offer, state):
    text = _original_offer_text(offer, state)
    history = list((state or {}).get("history") or [])
    if not history:
        return text

    lines = []
    for index, item in enumerate(history[-8:], start=max(1, len(history) - 7)):
        when = str(item.get("date") or "—")[:10]
        stage = item.get("stage")
        if stage is None:
            label = "relance manuelle"
        elif int(stage) == 30:
            label = "suivi final J+30"
        else:
            label = f"suivi J+{int(stage)}"
        lines.append(f"  {index}. {when} — {label}")

    suffix = "\n\n📋 Historique des relances :\n" + "\n".join(lines)
    if len(history) > 8:
        suffix += f"\n  … {len(history) - 8} plus ancienne(s)"
    return text + suffix


guarded._offer_text = _offer_text_with_history
logger.info("ODS FOLLOW-UP PERSISTENCE ACTIVE: %s", _FOLLOWUP_JSON_PATH)
