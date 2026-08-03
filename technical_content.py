import re


TECHNICAL_HEADERS = {
    "services",
    "description des services",
    "portée des services",
    "mandat",
    "mandat court",
    "description du mandat",
}


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
