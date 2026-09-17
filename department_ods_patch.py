"""Department-aware ODS workflow for Structure, Civil and Geotechnical offers."""
import json
import re
import threading
from datetime import datetime

import app as legacy

ODS_ROOT = 'Metra Structure Inc/Offre de service'
DEPARTMENTS = {
    'STR': {
        'label': 'Structure',
        'header': 'Ingénierie des structures / Structural Engineering',
        'folder': 'Structure',
        'role': 'Président-Ingénieur en structure',
        'discipline': 'structural engineering',
        'discipline_fr': 'ingénierie des structures',
        'sequence': 'review of available documents, site work/relevé, structural analysis, design or technical recommendations, and the requested signed/sealed deliverable',
    },
    'CIV': {
        'label': 'Civil',
        'header': 'Génie civil / Civil Engineering',
        'folder': 'Civil',
        'role': 'Président-Ingénieur civil',
        'discipline': 'civil engineering',
        'discipline_fr': 'génie civil',
        'sequence': 'review of available documents and surveys, site observations/relevé when justified, civil analysis and calculations, design/recommendations, and the requested plans/report or signed/sealed deliverable',
    },
    'GEO': {
        'label': 'Géotechnique',
        'header': 'Génie géotechnique / Geotechnical Engineering',
        'folder': 'Geotechnic',
        'role': 'Président-Ingénieur',
        'discipline': 'geotechnical engineering',
        'discipline_fr': 'génie géotechnique',
        'sequence': 'review of available site information, field investigation/testing only when requested or justified, interpretation of soil/rock conditions, geotechnical analysis and recommendations, and the requested report or signed/sealed deliverable',
    },
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
    match = re.search(r'ODS\d{2}-\d{3,4}-(?:STR|CIV|GEO)-[A-Z]{3}', ods, re.I)
    if match:
        return match.group(0).upper()
    old = re.search(r'ODS\d{2}-\d{3,4}(?:-[A-Z]{3})?', ods, re.I)
    if old:
        return old.group(0).upper()
    return legacy.safe_archive_filename(ods or 'ODS')

legacy.offer_reference = offer_reference


def _archive_roots_to_scan():
    year = datetime.now().strftime('%Y')
    roots = [ODS_ROOT]
    for meta in DEPARTMENTS.values():
        roots.append(f"{ODS_ROOT}/{meta['folder']}")
    # Backward compatibility with the short-lived year/"Offres ..." layout.
    roots.extend([
        f'{ODS_ROOT}/{year}/Offres Structure',
        f'{ODS_ROOT}/{year}/Offres Civil',
        f'{ODS_ROOT}/{year}/Offres Géotechnique',
    ])
    return roots


def get_next_project_num_from_onedrive():
    year2 = datetime.now().strftime('%y')
    token = legacy.graph_access_token()
    sender = legacy.microsoft_email_config()['EMAIL_SENDER']
    numbers = []
    pattern = re.compile(rf'ODS{year2}-(\d{{1,4}})(?:-|\b)', re.I)
    for root in _archive_roots_to_scan():
        try:
            items = legacy.list_onedrive_children(token, sender, root)
        except Exception:
            continue
        for item in items:
            match = pattern.search(str(item.get('name') or ''))
            if match:
                numbers.append(int(match.group(1)))
    return str(max(numbers, default=80) + 1).zfill(3)

legacy.get_next_project_num = get_next_project_num_from_onedrive


def archive_ods_files(data, token, sender, pdf_bytes):
    """Archive into the three department folders visible in OneDrive."""
    dept_folder = DEPARTMENTS[_dept(data)]['folder']
    legacy.create_onedrive_folder(token, sender, ODS_ROOT, dept_folder)
    folder = f'{ODS_ROOT}/{dept_folder}'
    base_name = legacy.safe_archive_filename(data.get('odsNum') or 'ODS')
    excel = legacy.generate_excel(data)
    excel.seek(0)
    legacy.upload_onedrive_path(token, sender, f'{folder}/{base_name}.pdf', pdf_bytes, 'application/pdf')
    legacy.upload_onedrive_path(
        token,
        sender,
        f'{folder}/{base_name}.xlsx',
        excel.read(),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    return [f'{dept_folder}/{base_name}.pdf', f'{dept_folder}/{base_name}.xlsx']

legacy.archive_ods_files = archive_ods_files


def project_year_and_code(data):
    """Keep the technical 3-letter code for project folders, not STR/CIV/GEO."""
    ods = str(data.get('odsNum') or '')
    current = re.search(r'ODS(\d{2})-\d{3,4}-(?:STR|CIV|GEO)-([A-Z]{3})', ods, re.I)
    if current:
        return f"20{current.group(1)}", current.group(2).upper()
    old = re.search(r'ODS(\d{2})-\d{3,4}-([A-Z]{3})', ods, re.I)
    if old:
        return f"20{old.group(1)}", old.group(2).upper()
    return datetime.now().strftime('%Y'), str(data.get('file_code') or 'PRJ').upper()[:3]

legacy.project_year_and_code = project_year_and_code


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
            return _original_paragraph(_department_text(text, _pdf_department, meta), *args, **kwargs)

        legacy.Paragraph = paragraph
        try:
            return _original_generate_pdf(data)
        finally:
            legacy.Paragraph = _original_paragraph
            _pdf_department = 'STR'

legacy.generate_pdf = generate_pdf


_original_ask_desc_options = legacy.ask_desc_options


def ask_desc_options(chat_id, uid):
    """Generate discipline-specific technical ODS content."""
    uid = str(uid)
    d = legacy.user_data.get(uid, {})
    code = _dept(d, uid)
    meta = DEPARTMENTS[code]
    try:
        legacy.tg(chat_id, "✍️ Préparation du contenu technique de l’ODS...")
        service = d.get('service', '')
        raw_desc = d.get('desc', '')
        property_type = d.get('property_type', '')
        addr = d.get('addr', '')
        prompt = (
            f"You prepare {meta['discipline']} offers of service for {legacy.DISPLAY_BRAND}. "
            f"Write in mature, project-specific French appropriate to {meta['discipline_fr']}. "
            "Never invent a test, deliverable, quantity, investigation extent, code review, design task, "
            "or professional commitment that the client did not request or that the context does not justify. "
            "Avoid promotional wording. Prepare ONE proposal only, using this exact JSON schema: "
            "{\"project_title\":\"short professional title\","
            "\"file_code\":\"relevant 3-letter uppercase technical code\","
            "\"short_mandate\":\"one short professional paragraph, maximum 70 words\","
            "\"service_lines\":[\"line 1\",\"line 2\",\"line 3\",\"line 4\",\"line 5 if justified\"]}. "
            "Use 3 to 5 service lines. Each line must be a concrete engineering action or deliverable, short enough for an ODS table, "
            "and end without a period. Every line must be complete. Never use an ellipsis and never end with an unfinished connector. "
            f"Order services logically for this discipline: {meta['sequence']}. "
            "Do not add generic filler such as coordination, availability, meetings, communications, or administration unless requested. "
            "Use 'le cas échéant' only for genuinely conditional work. "
            "Client request/context: " + raw_desc + ". "
            "Initially detected service: " + service + ". Property/site: " + property_type + ". "
            "Project address: " + addr + ". Return ONLY valid JSON."
        )
        response = legacy.client.messages.create(
            model='claude-sonnet-4-6', max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}],
        )
        result = ''.join(b.text for b in response.content if hasattr(b, 'text'))
        result = result.replace('```json', '').replace('```', '').strip()
        proposal = json.loads(result)
        service_lines = [
            cleaned + ';'
            for line in proposal.get('service_lines', [])[:5]
            if (cleaned := legacy._clean_service_line(line))
        ]
        short_mandate = str(proposal.get('short_mandate') or raw_desc).strip()
        d['project_title'] = str(proposal.get('project_title') or service).strip()
        d['file_code'] = re.sub(r'[^A-Z]', '', str(proposal.get('file_code') or 'ODS').upper())[:3].ljust(3, 'X')
        d['desc'] = short_mandate
        d['service_lines'] = service_lines
        d['desc_options'] = [short_mandate]
        d['department'] = code
        legacy.user_data[uid] = d
        legacy.save_user_data()
        provisional_name = f"ODS{datetime.now().strftime('%y')}-XXX-{code}-{d['file_code']}-{d['project_title']}"
        msg_lines = [
            '📋 Proposition technique', '',
            'Département : ' + meta['label'],
            'Titre : ' + d['project_title'],
            'Nom du fichier : ' + provisional_name,
            '', 'Mandat court :', short_mandate, '', 'Services :',
        ]
        msg_lines.extend('• ' + line for line in service_lines)
        legacy.tg(chat_id, '\n'.join(msg_lines))
        legacy.tg(
            chat_id,
            "Confirmer ce contenu avant de compléter les paramètres de l’ODS?",
            [
                [{'text': '✅ Confirmer', 'callback_data': 'desc_0'}],
                [{'text': '✏️ Modifier le contenu technique', 'callback_data': 'desc_custom'}],
            ],
        )
    except Exception as exc:
        legacy.logger.exception('department-aware ask_desc_options error: %s', exc)
        # Fall back to the proven legacy flow rather than blocking the offer.
        return _original_ask_desc_options(chat_id, uid)

legacy.ask_desc_options = ask_desc_options


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
                legacy.req.post(
                    f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                    json={'callback_query_id': cb.get('id')}, timeout=3,
                )
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
        menu_commands = {
            '/annuler', '/cancel', '❌ Annuler', '/aide', '/help', '❓ Aide',
            '📁 Convertir une offre en projet', '🧾 Facturation', '🧾 Facturer un projet',
        }
        if text not in menu_commands and uid not in DEPT_BY_UID and not legacy.user_data.get(uid, {}).get('department'):
            ask_department(msg.get('chat', {}).get('id'), uid)
            return
    return _original_handle_update(data)

legacy.handle_update = handle_update
legacy.logger.warning('DEPARTMENT ODS PATCH ACTIVE v3: STR/CIV/GEO folders + discipline content + project code fix')
