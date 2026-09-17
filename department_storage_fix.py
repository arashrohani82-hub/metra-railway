"""Final ODS department storage, numbering, state and email identity fixes."""
import html
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
    if not code and uid is not None:
        code = str(dept_patch.DEPT_BY_UID.get(str(uid)) or '').upper()
    return code if code in dept_patch.DEPARTMENTS else 'STR'


def archive_ods_files(data, token, sender, pdf_bytes):
    code = _department_code(data=data)
    dept_folder = dept_patch.DEPARTMENTS[code]['folder']
    ods.create_onedrive_folder(token, sender, ODS_ROOT, dept_folder)
    folder = f'{ODS_ROOT}/{dept_folder}'
    base_name = ods.safe_archive_filename(data.get('odsNum') or 'ODS')
    excel = ods.generate_excel(data)
    excel.seek(0)
    ods.upload_onedrive_path(token, sender, f'{folder}/{base_name}.pdf', pdf_bytes, 'application/pdf')
    ods.upload_onedrive_path(token, sender, f'{folder}/{base_name}.xlsx', excel.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    ods.logger.warning('ODS ARCHIVE DEPARTMENT=%s PATH=%s', code, folder)
    return [f'{dept_folder}/{base_name}.pdf', f'{dept_folder}/{base_name}.xlsx']


ods.archive_ods_files = archive_ods_files
dept_patch.legacy.archive_ods_files = archive_ods_files


def get_next_project_num():
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
    next_num = max(numbers, default=0) + 1
    ods.logger.warning('ODS NEXT NUMBER DEPARTMENT=%s ROOT=%s NEXT=%03d', code, root, next_num)
    return str(next_num).zfill(3)


ods.get_next_project_num = get_next_project_num
dept_patch.legacy.get_next_project_num = get_next_project_num


# Critical state fix: app.py extraction replaces user_data[uid] and can erase the
# selected department. Restore it before ask_next_missing performs technical
# generation and department-specific numbering.
_original_ask_next_missing = ods.ask_next_missing


def ask_next_missing(chat_id, uid):
    uid = str(uid)
    previous = getattr(_CTX, 'uid', None)
    _CTX.uid = uid
    try:
        d = ods.user_data.get(uid, {})
        code = str(d.get('department') or dept_patch.DEPT_BY_UID.get(uid) or '').upper()
        if code in dept_patch.DEPARTMENTS:
            d['department'] = code
            ods.user_data[uid] = d
            ods.save_user_data()
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


ROLE_BY_DEPT = {
    'STR': 'Président – Ingénieur en structure',
    'CIV': 'Président – Ingénieur civil',
    'GEO': 'Président – Ingénieur / Génie géotechnique',
}


def build_email_preview(data):
    recipient = ods.valid_client_email(data.get('email'))
    name = ods.normalize_client_name(data.get('name'))
    last_name = name.split()[-1] if name else ''
    civility = ods.normalize_civility(data.get('civility'))
    greeting = f"Bonjour {civility} {last_name}," if civility in ('M.', 'Mme') and last_name else (f"Bonjour {name}," if name else 'Bonjour,')
    ods_num = str(data.get('odsNum') or 'ODS').strip()
    match = re.search(r'ODS\d{2}-\d{3,4}-(?:STR|CIV|GEO)(?:-[A-Z]{3})?', ods_num, re.I)
    ods_reference = match.group(0).upper() if match else ods_num
    project = str(data.get('project_title') or data.get('service') or 'votre projet').strip()
    address = ods.client_contact_fields(data)['address']
    role = ROLE_BY_DEPT[_department_code(data=data)]
    subject = f"Offre de service {ods_reference} – {project}"
    body = (
        f"{greeting}\n\n"
        f"Veuillez trouver ci-joint notre offre de service {ods_reference} concernant le mandat « {project} » pour le projet situé au {address}.\n\n"
        "N'hésitez pas à nous contacter pour toute question.\n\n"
        "Cordialement,\n\n"
        "Arash Rohani, ing., P.Eng.\n"
        f"{role}\n"
        f"{ods.DISPLAY_BRAND}\n"
        "a.rohani@metraconsultation.ca | (438) 867-4131"
    )
    return recipient, subject, body


ods.build_email_preview = build_email_preview
dept_patch.legacy.build_email_preview = build_email_preview


def email_body_html(body):
    before, _, after = body.partition('Cordialement,')
    paragraphs = [html.escape(part).replace('\n', '<br>') for part in before.strip().split('\n\n') if part.strip()]
    content = ''.join(f'<p>{paragraph}</p>' for paragraph in paragraphs)
    lines = [line.strip() for line in after.strip().splitlines() if line.strip()]
    role = next((line for line in lines if line.startswith('Président')), ROLE_BY_DEPT['STR'])
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;line-height:1.45;color:#1f1f1f">'
        f'{content}<p>Cordialement,</p>'
        '<div style="border-left:4px solid #f5a623;padding-left:12px;margin-top:16px">'
        '<strong style="font-size:12pt;color:#102a43">Arash Rohani, ing., P.Eng.</strong><br>'
        f'{html.escape(role)}<br>'
        f'<strong>{html.escape(ods.DISPLAY_BRAND)}</strong><br>'
        '<a href="mailto:a.rohani@metraconsultation.ca" style="color:#1155cc">a.rohani@metraconsultation.ca</a> | '
        '<a href="tel:+14388674131" style="color:#1155cc">(438) 867-4131</a><br>'
        '<a href="https://metraconsultation.ca" style="color:#1155cc">metraconsultation.ca</a>'
        '</div></div>'
    )


ods.email_body_html = email_body_html
dept_patch.legacy.email_body_html = email_body_html
ods.logger.warning('DEPARTMENT FINAL FIX ACTIVE: storage + numbering + state + email identity')
