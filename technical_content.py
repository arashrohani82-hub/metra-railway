import json
import os
import re
import secrets
import string
import threading


TECHNICAL_HEADERS = {
    "services",
    "description des services",
    "portée des services",
    "mandat",
    "mandat court",
    "description du mandat",
}


# ODS file codes are accounting/project identifiers. They must not be inferred
# from the service type (e.g. RES), because repeated semantic codes can collide.
# Reserve every generated code immediately so even abandoned drafts cannot reuse it.
_CODE_LOCK = threading.Lock()
_DATA_DIR = os.environ.get("DATA_DIR", "/data")
_CODE_REGISTRY = os.path.join(_DATA_DIR, "ods_file_codes.json")
_RESERVED_CODES = {"RES", "ODS", "XXX", "PRJ"}
_ODS_CODE_RE = re.compile(r"ODS\d{2}-\d{3}-([A-Z]{3})(?:-|\b)", re.I)


def _collect_codes(value, found):
    if isinstance(value, dict):
        direct = re.sub(r"[^A-Z]", "", str(value.get("file_code") or "").upper())[:3]
        if len(direct) == 3:
            found.add(direct)
        for item in value.values():
            _collect_codes(item, found)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_codes(item, found)
    elif isinstance(value, str):
        for match in _ODS_CODE_RE.finditer(value):
            found.add(match.group(1).upper())


def _used_ods_codes():
    used = set(_RESERVED_CODES)
    for filename in ("offre_history.json", "offre_user_data.json", "ods_file_codes.json"):
        path = os.path.join(_DATA_DIR, filename)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = _ORIGINAL_JSON_LOADS(handle.read())
                _collect_codes(payload, used)
        except Exception:
            # Code generation must never block the ODS workflow because an old
            # registry/history file is malformed or temporarily unreadable.
            continue
    return used


def _save_reserved_code(code):
    os.makedirs(_DATA_DIR, exist_ok=True)
    codes = []
    try:
        if os.path.exists(_CODE_REGISTRY):
            with open(_CODE_REGISTRY, "r", encoding="utf-8") as handle:
                current = _ORIGINAL_JSON_LOADS(handle.read())
            if isinstance(current, list):
                codes = [str(item).upper() for item in current]
    except Exception:
        codes = []
    if code not in codes:
        codes.append(code)
    tmp = _CODE_REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(codes, ensure_ascii=False))
    os.replace(tmp, _CODE_REGISTRY)


def generate_unique_ods_code():
    alphabet = string.ascii_uppercase
    with _CODE_LOCK:
        used = _used_ods_codes()
        # 26^3 = 17,576 combinations; this loop has ample room for the ODS volume.
        for _ in range(20000):
            code = "".join(secrets.choice(alphabet) for _ in range(3))
            if code not in used:
                _save_reserved_code(code)
                return code
    raise RuntimeError("Aucun code ODS de trois lettres disponible")


# app.py currently asks the LLM for a semantic `file_code`. Intercept only that
# specific proposal JSON and replace the model's value with our unique identifier.
# Other JSON parsing in the bot is left unchanged.
_ORIGINAL_JSON_LOADS = json.loads


def _loads_with_unique_ods_code(payload, *args, **kwargs):
    parsed = _ORIGINAL_JSON_LOADS(payload, *args, **kwargs)
    if (
        isinstance(parsed, dict)
        and "project_title" in parsed
        and "short_mandate" in parsed
        and "service_lines" in parsed
        and "file_code" in parsed
    ):
        parsed["file_code"] = generate_unique_ods_code()
    return parsed


if not getattr(json.loads, "_metra_unique_ods_codes", False):
    _loads_with_unique_ods_code._metra_unique_ods_codes = True
    json.loads = _loads_with_unique_ods_code


def clean_service_line(value):
    line = re.sub(r"^\s*(?:[•\-*]|☐|✅|\d+[.)-])\s*", "", str(value or ""))
    line = re.sub(r"\s+", " ", line).strip().rstrip(".;")
    return line + ";" if line else ""


def parse_custom_technical_content(text, current_mandate="", max_services=5):
    """Interpret a manual edit as a mandate, service list, or both."""
    raw = str(text or "").strip()
    if not raw:
        return str(current_mandate or "").strip(), []

    mandate_parts = []
    services = []
    section = None

    for original_line in raw.splitlines():
        line = original_line.strip()
        if not line:
            continue
        header_match = re.match(r"^([^:]{2,40})\s*:\s*(.*)$", line)
        if header_match and header_match.group(1).strip().lower() in TECHNICAL_HEADERS:
            header = header_match.group(1).strip().lower()
            section = "services" if "service" in header else "mandate"
            line = header_match.group(2).strip()
            if not line:
                continue

        looks_like_service = bool(
            section == "services"
            or re.match(r"^\s*(?:[•\-*]|☐|✅|\d+[.)-])\s*", original_line)
            or line.endswith(";")
        )
        if looks_like_service:
            section = "services"
            candidates = [line]
            if line.count(";") > 1:
                candidates = [part for part in line.split(";") if part.strip()]
            for candidate in candidates:
                cleaned = clean_service_line(candidate)
                if cleaned and cleaned not in services:
                    services.append(cleaned)
        else:
            mandate_parts.append(line)

    if not services and raw.count(";") >= 2:
        services = [
            cleaned
            for cleaned in (clean_service_line(part) for part in raw.split(";"))
            if cleaned
        ]
        mandate_parts = []

    mandate = " ".join(mandate_parts).strip() or str(current_mandate or "").strip()
    return mandate, services[:max_services]
