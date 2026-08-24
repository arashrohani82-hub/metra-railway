import json
import os
import re
import secrets
import string
import threading
import sys
import time


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
        for _ in range(20000):
            code = "".join(secrets.choice(alphabet) for _ in range(3))
            if code not in used:
                _save_reserved_code(code)
                return code
    raise RuntimeError("Aucun code ODS de trois lettres disponible")


# app.py currently asks the LLM for a semantic `file_code`. Intercept only that
# specific proposal JSON and replace the model's value with our unique identifier.
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


# ---------------------------------------------------------------------------
# ODS number counter fix
# ---------------------------------------------------------------------------
# The old app increments ods_counter.json as soon as it merely *suggests* a
# number. Going back, editing, or abandoning a draft therefore burns numbers.
# We patch that behavior at runtime:
#   - suggestion = max(real sent/generated ODS numbers) + 1
#   - suggestion itself NEVER changes persistent state
#   - a number is committed only when Excel/PDF generation actually starts
# The old inflated ods_counter.json is intentionally ignored.
_NUMBER_LOCK = threading.Lock()
_COMMITTED_NUMBERS_FILE = os.path.join(_DATA_DIR, "ods_committed_numbers.json")


def _current_year_2():
    from datetime import datetime
    return datetime.now().strftime("%y")


def _collect_ods_numbers(value, year2, found):
    pattern = re.compile(rf"ODS{re.escape(year2)}-(\d{{1,4}})(?:-|\b)", re.I)
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_ods_numbers(key, year2, found)
            _collect_ods_numbers(item, year2, found)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_ods_numbers(item, year2, found)
    elif isinstance(value, str):
        for match in pattern.finditer(value):
            try:
                found.add(int(match.group(1)))
            except Exception:
                pass


def _load_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                return _ORIGINAL_JSON_LOADS(handle.read())
    except Exception:
        pass
    return default


def _real_used_ods_numbers():
    """Return numbers backed by a sent offer or an actually generated file."""
    year2 = _current_year_2()
    used = set()

    # Sent offers are the strongest source of truth. Draft sessions are excluded.
    history = _load_json_file(os.path.join(_DATA_DIR, "offre_history.json"), {})
    _collect_ods_numbers(history, year2, used)

    committed = _load_json_file(_COMMITTED_NUMBERS_FILE, {})
    if isinstance(committed, dict):
        for value in committed.get(year2, []):
            try:
                used.add(int(value))
            except Exception:
                pass
    return used


def next_real_ods_number():
    """Peek at the next number without consuming it."""
    with _NUMBER_LOCK:
        used = _real_used_ods_numbers()
        # Historical bot started around 080. If history exists, it controls.
        # Critically, we do NOT read the old inflated ods_counter.json.
        return str(max(used, default=80) + 1).zfill(3)


def commit_ods_number(data):
    """Consume a number only once actual PDF/Excel generation is requested."""
    year2 = _current_year_2()
    raw = str((data or {}).get("project_num") or "").strip()
    if not raw.isdigit():
        match = re.search(rf"ODS{re.escape(year2)}-(\d{{1,4}})", str((data or {}).get("odsNum") or ""), re.I)
        raw = match.group(1) if match else ""
    if not raw.isdigit():
        return
    number = int(raw)
    with _NUMBER_LOCK:
        payload = _load_json_file(_COMMITTED_NUMBERS_FILE, {})
        if not isinstance(payload, dict):
            payload = {}
        numbers = []
        for item in payload.get(year2, []):
            try:
                numbers.append(int(item))
            except Exception:
                pass
        if number not in numbers:
            numbers.append(number)
            numbers.sort()
        payload[year2] = numbers
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _COMMITTED_NUMBERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
        os.replace(tmp, _COMMITTED_NUMBERS_FILE)


def _find_app_module():
    mod = sys.modules.get("app")
    if mod is not None:
        return mod
    main = sys.modules.get("__main__")
    if main is not None and str(getattr(main, "__file__", "")).endswith("app.py"):
        return main
    return None


def _install_counter_patch():
    # technical_content.py is imported near the top of app.py, before app.py has
    # defined get_next_project_num/do_excel/do_pdf. Wait briefly for those names.
    for _ in range(300):
        mod = _find_app_module()
        if (
            mod is not None
            and hasattr(mod, "get_next_project_num")
            and hasattr(mod, "do_excel")
            and hasattr(mod, "do_pdf")
        ):
            if getattr(mod, "_metra_counter_patch_installed", False):
                return

            original_excel = mod.do_excel
            original_pdf = mod.do_pdf

            def _patched_get_next_project_num():
                return next_real_ods_number()

            def _patched_do_excel(chat_id, uid):
                data = getattr(mod, "user_data", {}).get(str(uid), {})
                commit_ods_number(data)
                return original_excel(chat_id, uid)

            def _patched_do_pdf(chat_id, uid):
                data = getattr(mod, "user_data", {}).get(str(uid), {})
                commit_ods_number(data)
                return original_pdf(chat_id, uid)

            mod.get_next_project_num = _patched_get_next_project_num
            mod.do_excel = _patched_do_excel
            mod.do_pdf = _patched_do_pdf
            mod._metra_counter_patch_installed = True
            return
        time.sleep(0.1)


threading.Thread(target=_install_counter_patch, daemon=True).start()


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
