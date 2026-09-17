"""Final ODS storage/numbering fix.

Ensures each department archives to its own top-level OneDrive folder and
suggests the next ODS number from that department only.
"""
import re
import threading
from datetime import datetime

import app as ods
import department_ods_patch as dept_patch

_CTX = threading.local()
ODS_ROOT = 'Metra Structure Inc/Offre de service'


def _department_code(data=None, uid=None):
    code = str((data or {}).get('department') or '').upper()
    if not code and uid is not None:
        code = str(ods.user_data.get(str(uid), {}).get('department') or '').upper()
    return code if code in dept_patch.DEPARTMENTS else 'STR'


def archive_ods_files(data, token, sender, pdf_bytes):
    """Always save ODS PDF/XLSX inside Structure, Civil or Geotechnic."""
    code = _department_code(data=data)
    dept_folder = dept_patch.DEPARTMENTS[code]['folder']
    ods.create_onedrive_folder(token, sender, ODS_ROOT, dept_folder)
    folder = f'{ODS_ROOT}/{dept_folder}'
    base_name = ods.safe_archive_filename(data.get('odsNum') or 'ODS')

    excel = ods.generate_excel(data)
    excel.seek(0)
    ods.upload_onedrive_path(
        token, sender, f'{folder}/{base_name}.pdf', pdf_bytes, 'application/pdf'
    )
    ods.upload_onedrive_path(
        token,
        sender,
        f'{folder}/{base_name}.xlsx',
        excel.read(),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    ods.logger.warning('ODS ARCHIVE DEPARTMENT=%s PATH=%s', code, folder)
    return [f'{dept_folder}/{base_name}.pdf', f'{dept_folder}/{base_name}.xlsx']


ods.archive_ods_files = archive_ods_files
dept_patch.legacy.archive_ods_files = archive_ods_files


def get_next_project_num():
    """Read the last ODS number from the active department folder only."""
    uid = getattr(_CTX, 'uid', None)
    data = ods.user_data.get(str(uid), {}) if uid is not None else {}
    code = _department_code(data=data, uid=uid)
    dept_folder = dept_patch.DEPARTMENTS[code]['folder']
    root = f'{ODS_ROOT}/{dept_folder}'

    year2 = datetime.now().strftime('%y')
    token = ods.graph_access_token()
    sender = ods.microsoft_email_config()['EMAIL_SENDER']
    pattern = re.compile(rf'ODS{year2}-(\d{{1,4}})(?:-|\b)', re.I)
    numbers = []
    try:
        items = ods.list_onedrive_children(token, sender, root)
        for item in items:
            match = pattern.search(str(item.get('name') or ''))
            if match:
                numbers.append(int(match.group(1)))
    except Exception as exc:
        ods.logger.exception('Department ODS numbering scan failed for %s: %s', root, exc)

    # For an empty department, start at 001. Existing departments continue from
    # their own highest number, independently of the other departments.
    next_num = max(numbers, default=0) + 1
    ods.logger.warning('ODS NEXT NUMBER DEPARTMENT=%s ROOT=%s NEXT=%03d', code, root, next_num)
    return str(next_num).zfill(3)


ods.get_next_project_num = get_next_project_num
dept_patch.legacy.get_next_project_num = get_next_project_num

_original_ask_next_missing = ods.ask_next_missing


def ask_next_missing(chat_id, uid):
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


ods.ask_next_missing = ask_next_missing
dept_patch.legacy.ask_next_missing = ask_next_missing

# Re-assign once more after all imports so functions resolving module globals use
# these final implementations.
ods.logger.warning('DEPARTMENT STORAGE FIX ACTIVE: per-folder archive + per-folder numbering')
