import logging
import re
from datetime import datetime

import project_followup_runtime as guarded

app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)


def get_next_offer_number_max_plus_one():
    """Return the next ODS number as highest archived number + 1, without consuming it."""
    year = datetime.now().strftime('%y')
    token = legacy.graph_access_token()
    sender = legacy.microsoft_email_config()['EMAIL_SENDER']
    items = legacy.list_onedrive_children(
        token,
        sender,
        'Metra Structure Inc/Offre de service',
    )
    pattern = re.compile(rf'ODS{year}-(\d{{1,4}})(?:-|\b)', re.I)
    numbers = []
    for item in items:
        match = pattern.search(str(item.get('name') or ''))
        if match:
            numbers.append(int(match.group(1)))

    latest = max(numbers, default=80)
    next_number = latest + 1
    result = str(next_number).zfill(3)
    logger.info(
        'ODS NUMBERING MAX+1 ACTIVE: latest=%s next=%s count=%s',
        latest,
        result,
        len(set(numbers)),
    )
    return result


legacy.get_next_project_num = get_next_offer_number_max_plus_one
logger.info('ODS NUMBERING POLICY: HIGHEST ARCHIVED NUMBER + 1')
