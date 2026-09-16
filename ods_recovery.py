"""Recover archived ODS offers when local Railway history was lost after deploys."""
import io
import re
from datetime import datetime

import openpyxl
import app as ods

ARCHIVE_ROOT = "Metra Structure Inc/Offre de service"
_original_show_pending_offers = ods.show_pending_offers


def _normalize_query(query):
    text = str(query or "").strip().upper()
    digits = re.search(r"(?:ODS\d{2}-)?(\d{1,4})", text)
    if not digits:
        return text
    return f"ODS{datetime.now().strftime('%y')}-{int(digits.group(1)):03d}"


def _cell_text(value, prefix=""):
    text = str(value or "").strip()
    if prefix and text.lower().startswith(prefix.lower()):
        text = text[len(prefix):].strip()
    return text


def _recover_from_xlsx(uid, query):
    ref = _normalize_query(query)
    if not re.fullmatch(r"ODS\d{2}-\d{3,4}", ref, re.I):
        return None

    # Do not overwrite an existing record.
    existing = ods.offers_history.get(str(uid), {}).get(ref)
    if existing:
        return ref

    token = ods.graph_access_token()
    sender = ods.microsoft_email_config()["EMAIL_SENDER"]
    items = ods.list_onedrive_children(token, sender, ARCHIVE_ROOT)
    candidates = []
    for item in items:
        name = str(item.get("name") or "")
        if name.lower().endswith(".xlsx") and ref.casefold() in name.casefold():
            candidates.append(name)
    if not candidates:
        return None

    # Prefer the shortest exact-style filename if multiple archived versions exist.
    filename = sorted(candidates, key=len)[0]
    raw = ods.download_onedrive_path(token, sender, f"{ARCHIVE_ROOT}/{filename}")
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=False)
    ws = wb["ODS"] if "ODS" in wb.sheetnames else wb[wb.sheetnames[0]]

    identity = _cell_text(ws["B7"].value)
    civility = "M./Mme"
    name = identity
    for prefix, value in (("Mme ", "Mme"), ("M. ", "M."), ("M ", "M.")):
        if identity.startswith(prefix):
            civility = value
            name = identity[len(prefix):].strip()
            break

    ods_cell = _cell_text(ws["B12"].value)
    match = re.search(r"ODS\d{2}-\d{3,4}(?:-[A-Z]{3})?", ods_cell, re.I)
    ods_num = match.group(0).upper() if match else ref
    desc = _cell_text(ws["B47"].value)
    data = {
        "name": ods.normalize_client_name(name),
        "civility": civility,
        "phone": _cell_text(ws["B9"].value, "Cell. :"),
        "email": _cell_text(ws["B10"].value, "Courriel :"),
        "addr": _cell_text(ws["B8"].value, "Adresse :"),
        "desc": desc,
        "service": desc,
        "project_title": desc.split("\n", 1)[0][:120] if desc else "Projet",
        "price": float(ws["E47"].value or 0),
        "odsNum": ods_num,
        "date": datetime.now().strftime("%Y-%m-%d"),
        # Archived XLSX exists only after the offer workflow produced/sent its files.
        "email_sent_at": datetime.now().isoformat(timespec="seconds"),
        "recovered_from_onedrive": True,
    }
    recovered_ref = ods.record_sent_offer(str(uid), data)
    ods.logger.warning("ODS RECOVERED FROM ONEDRIVE: %s file=%s", recovered_ref, filename)
    return recovered_ref


def show_pending_offers_with_recovery(chat_id, uid, query=""):
    # Normal history remains the primary source. Only query OneDrive when a
    # specific search has no local match, keeping the regular menu fast.
    if query and not ods.pending_offer_records(uid, query):
        try:
            _recover_from_xlsx(uid, query)
        except Exception as exc:
            ods.logger.exception("ODS OneDrive recovery failed: %s", exc)
    return _original_show_pending_offers(chat_id, uid, query)


ods.show_pending_offers = show_pending_offers_with_recovery
ods.logger.warning("ODS ONEDRIVE RECOVERY ACTIVE")
