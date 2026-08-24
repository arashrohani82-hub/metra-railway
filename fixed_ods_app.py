import re
from datetime import datetime

import app as legacy

app = legacy.app


def _first_available(numbers, start=81):
    used = {int(n) for n in numbers}
    candidate = start
    while candidate in used:
        candidate += 1
    return str(candidate).zfill(3)


def get_next_project_num_from_onedrive():
    """Read real archived ODS files and return first unused number without consuming it."""
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
    result = _first_available(numbers)
    legacy.logger.info('ODS numbering source=OneDrive next=%s used_max=%s', result, max(numbers, default=0))
    return result


# IMPORTANT: ask_next_missing() in app.py resolves this module-global function at call time.
# Replace the old counter-based function only after app.py has fully loaded.
legacy.get_next_project_num = get_next_project_num_from_onedrive
legacy.logger.info('ODS NUMBERING FIX ACTIVE: OneDrive first-gap strategy')
