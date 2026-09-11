import logging
import re
from datetime import datetime

import offer_followup_runtime as guarded

app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)


def _numbers_from_local_history(year):
    """Recover issued/saved ODS numbers when Microsoft Graph is unavailable."""
    pattern = re.compile(rf'ODS{year}-(\d{{1,4}})(?:-|\b)', re.I)
    numbers = []
    for records in (legacy.offers_history or {}).values():
        if not isinstance(records, dict):
            continue
        for ref, record in records.items():
            candidates = [ref]
            if isinstance(record, dict):
                data = record.get('data') or {}
                if isinstance(data, dict):
                    candidates.append(data.get('odsNum'))
            for candidate in candidates:
                match = pattern.search(str(candidate or ''))
                if match:
                    numbers.append(int(match.group(1)))
    return numbers


def get_next_offer_number_max_plus_one():
    """Return the next ODS number as highest archived number + 1, without consuming it."""
    year = datetime.now().strftime('%y')
    pattern = re.compile(rf'ODS{year}-(\d{{1,4}})(?:-|\b)', re.I)
    source = 'OneDrive'
    try:
        token = legacy.graph_access_token()
        sender = legacy.microsoft_email_config()['EMAIL_SENDER']
        items = legacy.list_onedrive_children(
            token,
            sender,
            'Metra Structure Inc/Offre de service',
        )
        numbers = []
        for item in items:
            match = pattern.search(str(item.get('name') or ''))
            if match:
                numbers.append(int(match.group(1)))
    except Exception as exc:
        # Renaming a Microsoft 365 mailbox can temporarily make the configured
        # Graph user unavailable. Number suggestion must not stop the entire
        # Telegram workflow; the persistent offer history is a safe fallback.
        source = 'local history fallback'
        numbers = _numbers_from_local_history(year)
        logger.exception(
            'ODS OneDrive numbering unavailable; using local history: %s', exc
        )

    latest = max(numbers, default=80)
    next_number = latest + 1
    result = str(next_number).zfill(3)
    logger.info(
        'ODS NUMBERING MAX+1 ACTIVE: latest=%s next=%s count=%s source=%s',
        latest, result, len(set(numbers)), source,
    )
    return result


legacy.get_next_project_num = get_next_offer_number_max_plus_one
logger.info('ODS NUMBERING POLICY: HIGHEST ARCHIVED NUMBER + 1')
