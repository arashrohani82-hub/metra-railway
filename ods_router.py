import base64
import hmac
import json
import os
import re
from datetime import datetime

from flask import jsonify, request

import app as ods

app = ods.app
ROUTER_SHARED_SECRET = os.getenv("ROUTER_SHARED_SECRET", "").strip()


def _first_available_number(numbers, start=81):
    """Return the first unused ODS number, ignoring isolated inflated/test numbers."""
    used = {int(n) for n in numbers if str(n).isdigit()}
    candidate = start
    while candidate in used:
        candidate += 1
    return str(candidate).zfill(3)


def _next_ods_number_from_onedrive():
    """Return first unused ODS number from actual archived ODS files, without consuming it."""
    year = datetime.now().strftime("%y")
    token = ods.graph_access_token()
    sender = ods.microsoft_email_config()["EMAIL_SENDER"]
    items = ods.list_onedrive_children(
        token,
        sender,
        "Metra Structure Inc/Offre de service",
    )
    numbers = []
    pattern = re.compile(rf"ODS{year}-(\d{{1,4}})(?:-|\b)", re.I)
    for item in items:
        name = str(item.get("name") or "")
        match = pattern.search(name)
        if match:
            try:
                numbers.append(int(match.group(1)))
            except Exception:
                pass
    return _first_available_number(numbers)


def _safe_next_ods_number():
    """Use real records only and choose the first gap; never touch the old local counter."""
    try:
        return _next_ods_number_from_onedrive()
    except Exception as exc:
        ods.logger.error("ODS OneDrive numbering lookup failed: %s", exc)
        year = datetime.now().strftime("%y")
        numbers = []
        pattern = re.compile(rf"ODS{year}-(\d{{1,4}})(?:-|\b)", re.I)
        for records in (ods.offers_history or {}).values():
            if not isinstance(records, dict):
                continue
            for ref, record in records.items():
                if not isinstance(record, dict) or not record.get("sent_at"):
                    continue
                match = pattern.search(str(ref))
                if match:
                    try:
                        numbers.append(int(match.group(1)))
                    except Exception:
                        pass
        return _first_available_number(numbers)


# All calls inside app.py now use this implementation. Merely displaying a
# suggestion never increments or persists any counter.
ods.get_next_project_num = _safe_next_ods_number


def _authorized():
    supplied = request.headers.get("X-Router-Secret", "")
    return bool(ROUTER_SHARED_SECRET) and hmac.compare_digest(supplied, ROUTER_SHARED_SECRET)


def _model_name():
    configured = os.getenv("ANTHROPIC_MODEL", "").strip()
    if configured:
        return configured
    try:
        models = list(ods.client.models.list(limit=50).data)
        sonnets = [m.id for m in models if "sonnet" in m.id.lower()]
        if sonnets:
            return sonnets[0]
        if models:
            return models[0].id
    except Exception:
        pass
    return "claude-sonnet-4-6"


def _json_text(response):
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    return json.loads(text.replace("```json", "").replace("```", "").strip())


@app.post("/router/classify-image")
def classify_image():
    if not _authorized():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    upload = request.files.get("image")
    if not upload:
        return jsonify({"ok": False, "error": "image_required"}), 400
    image = upload.read()
    if not image:
        return jsonify({"ok": False, "error": "empty_image"}), 400

    image_b64 = base64.b64encode(image).decode("ascii")
    model = _model_name()
    prompt = """Classify this image for a private engineering-company command center.
Return ONLY valid JSON with this schema:
{"route":"receipt|ods|inspection|guardian|unknown","confidence":0.0}
Rules:
- receipt = store receipt, invoice, payment slip, credit-card purchase receipt or expense document
- ods = client email/message/screenshot asking for engineering services, quote, inspection, design, report, permit help or proposal
- inspection = engineering site/defect/structural photo primarily showing a building condition rather than a request message
- guardian = letter, notice, official correspondence or document mainly requiring archive/follow-up
- unknown = none of the above
Choose the single best route."""
    try:
        response = ods.client.messages.create(
            model=model,
            max_tokens=180,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        result = _json_text(response)
        route = str(result.get("route") or "unknown").lower()
        if route not in {"receipt", "ods", "inspection", "guardian", "unknown"}:
            route = "unknown"
        return jsonify({"ok": True, "route": route, "confidence": float(result.get("confidence") or 0)})
    except Exception as exc:
        return jsonify({"ok": False, "error": "classification_failed", "detail": str(exc)[:180]}), 500


@app.post("/router/ods-extract")
def ods_extract():
    if not _authorized():
        return jsonify({"ok": False, "error": "forbidden"}), 403
    upload = request.files.get("image")
    if not upload:
        return jsonify({"ok": False, "error": "image_required"}), 400
    image = upload.read()
    try:
        user_id = str(int(request.form.get("user_id", "0")))
    except Exception:
        user_id = "0"
    if user_id == "0":
        return jsonify({"ok": False, "error": "invalid_user"}), 400

    image_b64 = base64.b64encode(image).decode("ascii")
    prompt = """Extract only information visibly present in this client engineering request or email screenshot. Read the full header and body. Do not invent missing information. Return ONLY JSON:
{"client_name":"","client_civility":"M.|Mme|M./Mme","phone":"","email":"","address":"","project_description":"","property_type":"","suggested_service":"","suggested_price":0}
Rules: An explicit self-identification in the body overrides a shortened or different From display name. From/sender email is the client email; To/recipient may be Metra Consultation and must not be used as client. Never return an @metrastructure.ca address as the client email. Extract a phone number written anywhere in the body or signature. Subject or body may contain the project address; preserve it exactly. project_description must retain the specific condition and every requested opinion, report, test or deliverable. suggested_price is only a preliminary internal CAD suggestion."""
    try:
        response = ods.client.messages.create(
            model=_model_name(), max_tokens=900,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        info = _json_text(response)
        service = str(info.get("suggested_service") or "").strip()
        price = int(info.get("suggested_price") or ods.PRICES.get(service, 3200))
        data = {
            "name": ods.normalize_client_name(info.get("client_name", "")),
            "civility": ods.normalize_civility(info.get("client_civility")),
            "phone": info.get("phone", ""),
            "email": info.get("email", ""),
            "addr": info.get("address", ""),
            "desc": info.get("project_description", ""),
            "property_type": info.get("property_type", ""),
            "service": service,
            "price": price,
            "odsNum": f"ODS{datetime.now().strftime('%y')}-{ods.get_next_project_num()}",
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        ods.user_data[user_id] = data
        ods.save_user_data()
        return jsonify({"ok": True, "ods": data})
    except Exception as exc:
        return jsonify({"ok": False, "error": "ods_extract_failed", "detail": str(exc)[:180]}), 500
