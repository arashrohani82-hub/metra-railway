import re
from datetime import datetime

from flask import jsonify

import app as legacy

app = legacy.app
VERSION = 'ods-numbering-v2-onedrive'


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
    legacy.logger.info(
        'ODS numbering source=OneDrive next=%s used_max=%s count=%s',
        result,
        max(numbers, default=0),
        len(set(numbers)),
    )
    return result


# Replace the legacy counter implementation after app.py has completely loaded.
legacy.get_next_project_num = get_next_project_num_from_onedrive
legacy.logger.info('ODS NUMBERING FIX ACTIVE: %s', VERSION)


@app.route('/debug/ods-number')
def debug_ods_number():
    """Temporary diagnostic endpoint: confirms the deployed code and numbering source."""
    try:
        next_number = get_next_project_num_from_onedrive()
        return jsonify({
            'ok': True,
            'version': VERSION,
            'next_number': next_number,
            'function': getattr(legacy.get_next_project_num, '__name__', ''),
        })
    except Exception as exc:
        return jsonify({
            'ok': False,
            'version': VERSION,
            'error': str(exc),
            'function': getattr(legacy.get_next_project_num, '__name__', ''),
        }), 500
