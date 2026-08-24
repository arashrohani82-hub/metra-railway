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
            temperature=0,
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
    prompt = """Extract only information visibly present in this client engineering request or email screenshot. Do not invent missing information. Return ONLY JSON:
{"client_name":"","client_civility":"M.|Mme|M./Mme","phone":"","email":"","address":"","project_description":"","property_type":"","suggested_service":"","suggested_price":0}
Rules: From/sender is the client; To/recipient may be Metra and must not be used as client. Subject may contain project address. Preserve visible address exactly. suggested_price is only a preliminary internal CAD suggestion."""
    try:
        response = ods.client.messages.create(
            model=_model_name(), max_tokens=900, temperature=0,
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
