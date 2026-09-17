import base64
import html
import logging
import os
import re
import threading
import urllib.parse
from datetime import datetime

import followup_persistence_runtime as guarded
import department_ods_patch as dept_patch

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
        uid = str(uid)
        code = str((legacy.user_data.get(uid, {}) or {}).get('department') or '').upper()
        if code in DEPARTMENT_FOLDERS:
            return code
        code = str(dept_patch.DEPT_BY_UID.get(uid) or '').upper()
        if code in DEPARTMENT_FOLDERS:
            legacy.user_data.setdefault(uid, {})['department'] = code
            legacy.save_user_data()
            logger.info('ODS DEPARTMENT RESTORED uid=%s department=%s source=DEPT_BY_UID', uid, code)
            return code

    # Last-resort lookup: when extraction replaced user_data but the Telegram
    # department selector already recorded the choice in DEPT_BY_UID.
    if len(dept_patch.DEPT_BY_UID) == 1:
        code = str(next(iter(dept_patch.DEPT_BY_UID.values())) or '').upper()
        if code in DEPARTMENT_FOLDERS:
            logger.info('ODS DEPARTMENT FALLBACK department=%s source=single DEPT_BY_UID', code)
            return code
    return 'STR'


def _ensure_department(data=None, uid=None):
    previous = getattr(_CTX, 'uid', None)
    if uid is not None:
        _CTX.uid = str(uid)
    try:
        code = _active_department(data)
        if isinstance(data, dict) and data.get('department') != code:
            data['department'] = code
        if uid is not None:
            uid = str(uid)
            legacy.user_data.setdefault(uid, {})['department'] = code
            legacy.save_user_data()
        return code
    finally:
        if uid is not None:
            if previous is None:
                try:
                    delattr(_CTX, 'uid')
                except AttributeError:
                    pass
            else:
                _CTX.uid = previous


def _numbers_from_local_history(year, department):
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
        logger.exception('ODS department numbering unavailable for %s; using local history: %s', root, exc)

    latest = max(numbers, default=0)
    result = str(latest + 1).zfill(3)
    logger.info(
        'ODS NUMBERING DEPARTMENT=%s latest=%s next=%s count=%s source=%s',
        department, latest, result, len(set(numbers)), source,
    )
    return result


legacy.get_next_project_num = get_next_offer_number_max_plus_one

_original_ask_next_missing = legacy.ask_next_missing


def ask_next_missing_with_department_context(chat_id, uid):
    previous = getattr(_CTX, 'uid', None)
    _CTX.uid = str(uid)
    try:
        d = legacy.user_data.get(str(uid), {})
        _ensure_department(d, uid)
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
    department = _ensure_department(data)
    folder_name = DEPARTMENT_FOLDERS[department]
    legacy.create_onedrive_folder(token, sender, ODS_ROOT, folder_name)
    target = f'{ODS_ROOT}/{folder_name}'
    base_name = legacy.safe_archive_filename(data.get('odsNum') or 'ODS')

    excel = legacy.generate_excel(data)
    excel.seek(0)
    legacy.upload_onedrive_path(token, sender, f'{target}/{base_name}.pdf', pdf_bytes, 'application/pdf')
    legacy.upload_onedrive_path(
        token, sender, f'{target}/{base_name}.xlsx', excel.read(),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    logger.info('ODS ARCHIVE DEPARTMENT=%s TARGET=%s', department, target)
    return [f'{folder_name}/{base_name}.pdf', f'{folder_name}/{base_name}.xlsx']


legacy.archive_ods_files = archive_ods_files_by_department


def _greeting(data):
    civility = str(data.get('civility') or '').strip()
    name = str(data.get('name') or '').strip()
    if civility and name:
        return f'{civility} {name}'
    return name or 'Madame, Monsieur'


def _email_html(data, reference):
    greeting = html.escape(_greeting(data))
    address = html.escape(str(data.get('addr') or '').strip().replace('\n', ', '))
    project_title = str(data.get('project_title') or data.get('service') or 'votre projet').strip()
    project_title = html.escape(project_title)
    department = _ensure_department(data)
    role = {
        'STR': 'Président – Ingénieur en structure',
        'CIV': 'Président – Ingénieur civil',
        'GEO': 'Président – Ingénieur en géotechnique',
    }[department]
    return f'''<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.55;color:#202124;">
<p>Bonjour {greeting},</p>
<p>Veuillez trouver ci-joint notre offre de service <strong>{html.escape(reference)}</strong> concernant le mandat « {project_title} » pour le projet situé au <strong>{address}</strong>.</p>
<p>N'hésitez pas à nous contacter pour toute question.</p>
<p>Cordialement,</p>
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-top:10px;">
<tr>
<td style="vertical-align:middle;padding-right:14px;"><img src="cid:metra-logo" alt="Metra Consultation" width="145" style="display:block;width:145px;height:auto;border:0;"></td>
<td style="vertical-align:top;border-left:4px solid #f5a623;padding-left:14px;">
<div style="font-size:18px;font-weight:700;color:#12324a;">Arash Rohani, ing., P.Eng.</div>
<div style="font-size:15px;margin-top:2px;">{role}</div>
<div style="font-size:16px;font-weight:700;margin-top:4px;">Metra Consultation Inc.</div>
<div style="font-size:14px;margin-top:5px;"><a href="mailto:a.rohani@metraconsultation.ca" style="color:#1155cc;">a.rohani@metraconsultation.ca</a> | <a href="tel:+14388674131" style="color:#1155cc;">(438) 867-4131</a></div>
<div style="font-size:14px;margin-top:2px;"><a href="https://metraconsultation.ca" style="color:#1155cc;">metraconsultation.ca</a></div>
</td>
</tr>
</table>
</div>'''


def send_ods_email_branded(data):
    """Active production sender: clean body + CID logo + department-safe identity."""
    _ensure_department(data)
    recipient = legacy.valid_client_email(data.get('email'))
    if not recipient:
        raise ValueError('Le courriel du client est manquant ou invalide.')

    reference = legacy.offer_reference(data)
    subject = f'Offre de service {reference} - {data.get("project_title") or data.get("service") or "Projet"}'
    pdf = legacy.generate_pdf(data)
    pdf.seek(0)
    pdf_bytes = pdf.read()
    filename = '{}_{}.pdf'.format(
        data.get('odsNum', 'ODS'),
        (data.get('name') or 'client').replace(' ', '-'),
    )

    try:
        with open(legacy.LOGOS['metra'], 'rb') as logo_file:
            logo_b64 = base64.b64encode(logo_file.read()).decode('ascii')
    except Exception as exc:
        logger.exception('Unable to load Metra email logo: %s', exc)
        logo_b64 = ''

    attachments = [{
        '@odata.type': '#microsoft.graph.fileAttachment',
        'name': filename,
        'contentType': 'application/pdf',
        'contentBytes': base64.b64encode(pdf_bytes).decode('ascii'),
    }]
    if logo_b64:
        attachments.append({
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': 'metra-logo.png',
            'contentType': 'image/png',
            'contentBytes': logo_b64,
            'contentId': 'metra-logo',
            'isInline': True,
        })

    payload = {
        'message': {
            'subject': subject,
            'body': {'contentType': 'HTML', 'content': _email_html(data, reference)},
            'toRecipients': [{'emailAddress': {'address': recipient}}],
            'attachments': attachments,
        },
        'saveToSentItems': True,
    }
    config = legacy.microsoft_email_config()
    token = legacy.graph_access_token()
    sender = urllib.parse.quote(config['EMAIL_SENDER'], safe='')
    response = legacy.req.post(
        f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json=payload,
        timeout=45,
    )
    if response.status_code != 202:
        logger.error('Microsoft sendMail error: %s %s', response.status_code, response.text[:500])
        raise RuntimeError("Microsoft 365 a refusé l'envoi du courriel.")

    archive_files = []
    archive_error = None
    try:
        archive_files = archive_ods_files_by_department(data, token, config['EMAIL_SENDER'], pdf_bytes)
    except Exception as exc:
        archive_error = str(exc)
        logger.error('OneDrive ODS archive error: %s', exc)

    logger.info('ODS BRANDED EMAIL SENT reference=%s department=%s inline_logo=%s website=metraconsultation.ca', reference, _active_department(data), bool(logo_b64))
    return recipient, subject, archive_files, archive_error


legacy.send_ods_email = send_ods_email_branded

logger.info('ODS NUMBERING POLICY: PER-DEPARTMENT HIGHEST + 1')
logger.info('ODS ARCHIVE POLICY: Structure/Civil/Geotechnic folders')
logger.info('ODS DEPARTMENT POLICY: selector state survives extraction via DEPT_BY_UID')
logger.info('ODS EMAIL POLICY: DIRECT BRANDED SENDER + CID LOGO + metraconsultation.ca')

import offer_potential_runtime  # noqa: E402,F401
from household_bot import init_household_bot  # noqa: E402
init_household_bot(app)
