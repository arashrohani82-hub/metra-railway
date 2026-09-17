import logging
import os
import re
import threading
from datetime import datetime

import followup_persistence_runtime as guarded

app = guarded.app
legacy = guarded.legacy
logger = logging.getLogger(__name__)

ODS_ROOT = 'Metra Structure Inc/Offre de service'
DEPARTMENT_FOLDERS = {
    'STR': 'Structure',
    'CIV': 'Civil',
    'GEO': 'Geotechnic',
}
_CTX = threading.local()


def _active_department(data=None):
    code = str((data or {}).get('department') or '').upper()
    if code in DEPARTMENT_FOLDERS:
        return code
    uid = getattr(_CTX, 'uid', None)
    if uid is not None:
        code = str((legacy.user_data.get(str(uid), {}) or {}).get('department') or '').upper()
        if code in DEPARTMENT_FOLDERS:
            return code
    # Safe legacy default: old offers were structural.
    return 'STR'


def _numbers_from_local_history(year, department):
    """Recover issued/saved ODS numbers for one department only."""
    pattern = re.compile(rf'ODS{year}-(\d{{1,4}})-{department}(?:-|\b)', re.I)
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
    """Return next ODS number from the selected department folder only."""
    year = datetime.now().strftime('%y')
    department = _active_department()
    folder = DEPARTMENT_FOLDERS[department]
    root = f'{ODS_ROOT}/{folder}'
    pattern = re.compile(rf'ODS{year}-(\d{{1,4}})(?:-|\b)', re.I)
    source = root
    numbers = []
    try:
        token = legacy.graph_access_token()
        sender = legacy.microsoft_email_config()['EMAIL_SENDER']
        items = legacy.list_onedrive_children(token, sender, root)
        for item in items:
            match = pattern.search(str(item.get('name') or ''))
            if match:
                numbers.append(int(match.group(1)))
    except Exception as exc:
        source = 'local history fallback'
        numbers = _numbers_from_local_history(year, department)
        logger.exception(
            'ODS department numbering unavailable for %s; using local history: %s',
            root,
            exc,
        )

    # Independent sequence for each department. Empty folder starts at 001.
    latest = max(numbers, default=0)
    next_number = latest + 1
    result = str(next_number).zfill(3)
    logger.info(
        'ODS NUMBERING DEPARTMENT=%s latest=%s next=%s count=%s source=%s',
        department,
        latest,
        result,
        len(set(numbers)),
        source,
    )
    return result


legacy.get_next_project_num = get_next_offer_number_max_plus_one

# Keep the uid available while ask_next_missing asks for the suggested ODS number.
_original_ask_next_missing = legacy.ask_next_missing


def ask_next_missing_with_department_context(chat_id, uid):
    previous = getattr(_CTX, 'uid', None)
    _CTX.uid = str(uid)
    try:
        return _original_ask_next_missing(chat_id, uid)
    finally:
        if previous is None:
            try:
                delattr(_CTX, 'uid')
            except AttributeError:
                pass
        else:
            _CTX.uid = previous


legacy.ask_next_missing = ask_next_missing_with_department_context


def archive_ods_files_by_department(data, token, sender, pdf_bytes):
    """Always archive final PDF/XLSX in the selected department folder."""
    department = _active_department(data)
    folder_name = DEPARTMENT_FOLDERS[department]
    legacy.create_onedrive_folder(token, sender, ODS_ROOT, folder_name)
    target = f'{ODS_ROOT}/{folder_name}'
    base_name = legacy.safe_archive_filename(data.get('odsNum') or 'ODS')

    excel = legacy.generate_excel(data)
    excel.seek(0)
    legacy.upload_onedrive_path(
        token,
        sender,
        f'{target}/{base_name}.pdf',
        pdf_bytes,
        'application/pdf',
    )
    legacy.upload_onedrive_path(
        token,
        sender,
        f'{target}/{base_name}.xlsx',
        excel.read(),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    logger.info('ODS ARCHIVE DEPARTMENT=%s TARGET=%s', department, target)
    return [f'{folder_name}/{base_name}.pdf', f'{folder_name}/{base_name}.xlsx']


legacy.archive_ods_files = archive_ods_files_by_department

logger.info('ODS NUMBERING POLICY: PER-DEPARTMENT HIGHEST + 1')
logger.info('ODS ARCHIVE POLICY: Structure/Civil/Geotechnic folders')

# Load the lead-priority layer last so it can wrap the complete follow-up flow.
import offer_potential_runtime  # noqa: E402,F401

# The household assistant is a separate Telegram bot sharing this web process.
# It remains completely inactive until HOUSEHOLD_BOT_TOKEN is configured.
from household_bot import init_household_bot  # noqa: E402

init_household_bot(app)
