"""Department-aware ODS workflow for Structure, Civil and Geotechnical offers."""
import re
import threading
from datetime import datetime

import app as legacy

DEPARTMENTS = {
    'STR': {'label': 'Structure', 'header': 'Ingénierie des structures / Structural Engineering', 'folder': 'Offres Structure', 'role': 'Président-Ingénieur en structure'},
    'CIV': {'label': 'Civil', 'header': 'Génie civil / Civil Engineering', 'folder': 'Offres Civil', 'role': 'Président-Ingénieur civil'},
    'GEO': {'label': 'Géotechnique', 'header': 'Génie géotechnique / Geotechnical Engineering', 'folder': 'Offres Géotechnique', 'role': 'Président-Ingénieur'},
}
DEPT_BY_UID = {}
_pdf_lock = threading.Lock()
_pdf_department = 'STR'


def _dept(data=None, uid=None):
    code = str((data or {}).get('department') or DEPT_BY_UID.get(str(uid), 'STR')).upper()
    return code if code in DEPARTMENTS else 'STR'


def ask_department(chat_id, uid):
    legacy.tg(chat_id, "🏢 Pour quel département est cette offre ?", [
        [{'text': '🏗️ Structure', 'callback_data': 'dept:STR'}],
        [{'text': '🛣️ Civil', 'callback_data': 'dept:CIV'}],
        [{'text': '🧪 Géotechnique', 'callback_data': 'dept:GEO'}],
    ])


def build_ods_num(data):
    yr = datetime.now().strftime('%y')
    num = str(data.get('project_num') or '000').zfill(3)
    dept = _dept(data)
    addr = str(data.get('addr') or '')
    lines = [line.strip() for line in addr.split('\n') if line.strip()]
    city = lines[1] if len(lines) >= 2 else (lines[0] if lines else '')
    a = city[0].upper() if city else 'X'
    name = str(data.get('name') or '')
    b = name[0].upper() if name else 'X'
    service = str(data.get('service') or '')
    c = service[0].upper() if service else 'X'
    technical = re.sub(r'[^A-Z]', '', str(data.get('file_code') or '').upper())[:3]
    if len(technical) != 3:
        technical = f'{a}{b}{c}'
    return f'ODS{yr}-{num}-{dept}-{technical}'

legacy.build_ods_num = build_ods_num


def offer_reference(data):
    ods = str(data.get('odsNum') or '')
    match = re.search(r'ODS\d{2}-\d{3}-(?:STR|CIV|GEO)-[A-Z]{3}', ods, re.I)
    if match:
        return match.group(0).upper()
    old = re.search(r'ODS\d{2}-\d{3}-[A-Z]{3}', ods, re.I)
    if old:
        return old.group(0).upper()
    return legacy.safe_archive_filename(ods or 'ODS')

legacy.offer_reference = offer_reference


def get_next_project_num_from_onedrive():
    year2 = datetime.now().strftime('%y')
    year4 = datetime.now().strftime('%Y')
    token = legacy.graph_access_token()
    sender = legacy.microsoft_email_config()['EMAIL_SENDER']
    roots = ['Metra Structure Inc/Offre de service']
    roots.extend(f"Metra Structure Inc/Offre de service/{year4}/{m['folder']}" for m in DEPARTMENTS.values())
    numbers = []
    pattern = re.compile(rf'ODS{year2}-(\d{{1,4}})(?:-|\b)', re.I)
    for root in roots:
        try:
            items = legacy.list_onedrive_children(token, sender, root)
        except Exception:
            continue
        for item in items:
            m = pattern.search(str(item.get('name') or ''))
            if m:
                numbers.append(int(m.group(1)))
    return str(max(numbers, default=80) + 1).zfill(3)

legacy.get_next_project_num = get_next_project_num_from_onedrive


def archive_ods_files(data, token, sender, pdf_bytes):
    root = 'Metra Structure Inc/Offre de service'
    year = datetime.now().strftime('%Y')
    legacy.create_onedrive_folder(token, sender, root, year)
    year_root = f'{root}/{year}'
    dept_folder = DEPARTMENTS[_dept(data)]['folder']
    legacy.create_onedrive_folder(token, sender, year_root, dept_folder)
    folder = f'{year_root}/{dept_folder}'
    base_name = legacy.safe_archive_filename(data.get('odsNum') or 'ODS')
    excel = legacy.generate_excel(data)
    excel.seek(0)
    legacy.upload_onedrive_path(token, sender, f'{folder}/{base_name}.pdf', pdf_bytes, 'application/pdf')
    legacy.upload_onedrive_path(token, sender, f'{folder}/{base_name}.xlsx', excel.read(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return [f'{folder}/{base_name}.pdf', f'{folder}/{base_name}.xlsx']

legacy.archive_ods_files = archive_ods_files

_original_generate_pdf = legacy.generate_pdf
_original_paragraph = legacy.Paragraph
_original_draw_header_footer = legacy.draw_header_footer


def draw_header_footer(canvas, doc):
    if _pdf_department == 'STR':
        return _original_draw_header_footer(canvas, doc)
    meta = DEPARTMENTS[_pdf_department]
    canvas.saveState()
    canvas.drawImage(legacy.LOGOS['metra'], 1.8*legacy.cm, legacy.H-2.85*legacy.cm, width=3.6*legacy.cm, height=1.35*legacy.cm, preserveAspectRatio=True, mask='auto')
    canvas.setFillColor(legacy.BLACK)
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawCentredString(legacy.W/2, legacy.H-1.7*legacy.cm, meta['header'])
    canvas.setFont('Helvetica', 9)
    canvas.drawCentredString(legacy.W/2, legacy.H-2.2*legacy.cm, '1610-1280 Rue Saint-Jacques')
    canvas.drawCentredString(legacy.W/2, legacy.H-2.7*legacy.cm, 'Montréal – Québec- Canada  H3C 0G1')
    canvas.setFillColor(legacy.colors.HexColor('#1155CC'))
    canvas.drawCentredString(legacy.W/2, legacy.H-3.2*legacy.cm, 'info@metraconsultation.ca | (438) 867-4131')
    canvas.setFillColor(legacy.BLACK)
    canvas.setLineWidth(1)
    canvas.line(1.8*legacy.cm, legacy.H-3.6*legacy.cm, legacy.W-1.8*legacy.cm, legacy.H-3.6*legacy.cm)
    canvas.setLineWidth(0.5)
    canvas.line(1.8*legacy.cm, 2.0*legacy.cm, legacy.W-1.8*legacy.cm, 2.0*legacy.cm)
    canvas.drawImage(legacy.LOGOS['ing'], 2*legacy.cm, .3*legacy.cm, width=2*legacy.cm, height=1.4*legacy.cm, preserveAspectRatio=True, mask='auto')
    canvas.drawImage(legacy.LOGOS['peo'], 8*legacy.cm, .3*legacy.cm, width=3*legacy.cm, height=1.4*legacy.cm, preserveAspectRatio=True, mask='auto')
    canvas.drawImage(legacy.LOGOS['rgcq'], 15*legacy.cm, .3*legacy.cm, width=2*legacy.cm, height=1.4*legacy.cm, preserveAspectRatio=True, mask='auto')
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(legacy.W-1.8*legacy.cm, .6*legacy.cm, f'{doc.page} | Page')
    canvas.restoreState()

legacy.draw_header_footer = draw_header_footer


def _department_text(text, code, meta):
    if not isinstance(text, str) or code == 'STR':
        return text
    text = text.replace('Président-Ingénieur en structure', meta['role'])
    text = text.replace('Ingénierie des structures / Structural Engineering', meta['header'])
    if code == 'CIV':
        text = text.replace(
            "Metra Consultation Inc. offre ses services d'ingénierie-conseil conformément aux cadres légaux, aux normes en vigueur et aux règles professionnelles applicables, notamment celles de l'Ordre des ingénieurs du Québec (OIQ) et de Professional Engineers Ontario (PEO), pour le périmètre défini au mandat.",
            "Metra Consultation Inc. offre ses services de génie civil conformément aux cadres légaux, aux normes en vigueur et aux règles professionnelles applicables, notamment celles de l'Ordre des ingénieurs du Québec (OIQ) et de Professional Engineers Ontario (PEO), pour le périmètre défini au mandat."
        )
        text = text.replace(
            "Toute requête de déplacement doit être transmise au moins 48 heures avant la date prévue.",
            "Toute visite ou intervention sur site doit être coordonnée avec le client au moins 48 heures à l'avance. Le client doit assurer un accès sécuritaire aux zones visées et transmettre les plans, relevés et informations disponibles nécessaires au mandat."
        )
        text = text.replace(
            "Plans architecturaux fournis avant le début du mandat (si disponible);",
            "Plans, relevés, certificat de localisation et informations existantes fournis avant le début du mandat, selon leur disponibilité;"
        )
    elif code == 'GEO':
        text = text.replace(
            "Metra Consultation Inc. offre ses services d'ingénierie-conseil conformément aux cadres légaux, aux normes en vigueur et aux règles professionnelles applicables, notamment celles de l'Ordre des ingénieurs du Québec (OIQ) et de Professional Engineers Ontario (PEO), pour le périmètre défini au mandat.",
            "Metra Consultation Inc. offre ses services de génie géotechnique conformément aux cadres légaux, aux normes en vigueur et aux règles professionnelles applicables, notamment celles de l'Ordre des ingénieurs du Québec (OIQ) et de Professional Engineers Ontario (PEO), pour le périmètre défini au mandat."
        )
        text = text.replace(
            "Toute requête de déplacement doit être transmise au moins 48 heures avant la date prévue.",
            "Les travaux de terrain sont assujettis à l'accessibilité du site, à la localisation préalable des services souterrains et aux autorisations requises. Le client doit assurer un accès sécuritaire aux points d'investigation et signaler toute contrainte connue avant la mobilisation."
        )
        text = text.replace(
            "Plans architecturaux fournis avant le début du mandat (si disponible);",
            "Plans disponibles, localisation des ouvrages projetés et informations pertinentes sur le site fournis avant le début du mandat;"
        )
    return text


def generate_pdf(data):
    global _pdf_department
    with _pdf_lock:
        _pdf_department = _dept(data)
        meta = DEPARTMENTS[_pdf_department]
        def paragraph(text, *args, **kwargs):
            # Only non-table/general ODS content is department-adapted here.
            # The project fee/services table remains driven by the existing offer data.
            return _original_paragraph(_department_text(text, _pdf_department, meta), *args, **kwargs)
        legacy.Paragraph = paragraph
        try:
            return _original_generate_pdf(data)
        finally:
            legacy.Paragraph = _original_paragraph
            _pdf_department = 'STR'

legacy.generate_pdf = generate_pdf

_original_extract_text = legacy.do_extract_text
_original_extract_many = legacy.do_extract_many


def do_extract_text(chat_id, uid, text):
    uid = str(uid)
    dept = DEPT_BY_UID.get(uid) or legacy.user_data.get(uid, {}).get('department')
    if dept:
        DEPT_BY_UID[uid] = dept
        legacy.user_data.setdefault(uid, {})['department'] = dept
        legacy.save_user_data()
    result = _original_extract_text(chat_id, uid, text)
    if dept and uid in legacy.user_data:
        legacy.user_data[uid]['department'] = dept
        legacy.save_user_data()
    return result


def do_extract_many(chat_id, uid, file_ids):
    uid = str(uid)
    dept = DEPT_BY_UID.get(uid) or legacy.user_data.get(uid, {}).get('department')
    if dept:
        DEPT_BY_UID[uid] = dept
        legacy.user_data.setdefault(uid, {})['department'] = dept
        legacy.save_user_data()
    result = _original_extract_many(chat_id, uid, file_ids)
    if dept and uid in legacy.user_data:
        legacy.user_data[uid]['department'] = dept
        legacy.save_user_data()
    return result

legacy.do_extract_text = do_extract_text
legacy.do_extract_many = do_extract_many

_original_handle_update = legacy.handle_update


def handle_update(data):
    msg = data.get('message', {})
    cb = data.get('callback_query', {})
    if cb:
        cdata = cb.get('data', '')
        if cdata.startswith('dept:'):
            uid = str(cb.get('from', {}).get('id'))
            chat_id = cb.get('message', {}).get('chat', {}).get('id')
            code = cdata.split(':', 1)[1].upper()
            if code not in DEPARTMENTS:
                return
            try:
                legacy.req.post(f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery', json={'callback_query_id': cb.get('id')}, timeout=3)
            except Exception:
                pass
            DEPT_BY_UID[uid] = code
            legacy.user_data[uid] = {'department': code, 'date': datetime.now().strftime('%Y-%m-%d')}
            legacy.save_user_data()
            legacy.tg(chat_id, f"✅ Département : {DEPARTMENTS[code]['label']}\n\n📸 Envoyez une photo ou collez le texte/courriel du client.")
            return
        if cdata == 'nouveau':
            uid = str(cb.get('from', {}).get('id'))
            chat_id = cb.get('message', {}).get('chat', {}).get('id')
            legacy.user_data.pop(uid, None)
            DEPT_BY_UID.pop(uid, None)
            legacy.save_user_data()
            ask_department(chat_id, uid)
            return

    if msg and msg.get('text') in ('/start', '/nouveau', '📝 Nouvelle offre'):
        uid = str(msg.get('from', {}).get('id'))
        chat_id = msg.get('chat', {}).get('id')
        if msg.get('from', {}).get('id') not in legacy.ALLOWED_USERS:
            if chat_id:
                legacy.tg(chat_id, '⛔ Ce bot est privé.')
            return
        legacy.user_data.pop(uid, None)
        DEPT_BY_UID.pop(uid, None)
        legacy.save_user_data()
        legacy.tg(chat_id, f"👋 {legacy.DISPLAY_BRAND_SHORT} — Nouvelle offre", reply_markup=legacy.main_menu())
        ask_department(chat_id, uid)
        return

    if msg and (msg.get('text') or msg.get('photo')):
        uid = str(msg.get('from', {}).get('id'))
        text = msg.get('text', '')
        menu_commands = {'/annuler','/cancel','❌ Annuler','/aide','/help','❓ Aide','📁 Convertir une offre en projet','🧾 Facturation','🧾 Facturer un projet'}
        if text not in menu_commands and uid not in DEPT_BY_UID and not legacy.user_data.get(uid, {}).get('department'):
            ask_department(msg.get('chat', {}).get('id'), uid)
            return
    return _original_handle_update(data)

legacy.handle_update = handle_update
legacy.logger.warning('DEPARTMENT ODS PATCH ACTIVE: STR/CIV/GEO WITH DEPARTMENT-SPECIFIC NON-TABLE CONTENT')
