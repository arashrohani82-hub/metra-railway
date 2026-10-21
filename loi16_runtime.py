"""Short Quebec condominium proposal flow within Structure.

No client messages are sent automatically. The document checklist is shown to
the operator only after the existing accepted-offer/project conversion succeeds.
"""
import html
import io
import json
import os
import re
from datetime import datetime

import openpyxl
import reportlab
from reportlab.lib import colors
from openpyxl.styles import Alignment, Font
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Embed the fonts shipped with ReportLab so French accents and spacing do not
# depend on the recipient's PDF viewer or server font substitutions.
_FONT_DIR = os.path.join(os.path.dirname(reportlab.__file__), 'fonts')
pdfmetrics.registerFont(TTFont('Loi16Regular', os.path.join(_FONT_DIR, 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('Loi16Bold', os.path.join(_FONT_DIR, 'VeraBd.ttf')))

TITLE = "Carnet d’entretien et étude du fonds de prévoyance — Loi 16"
TITLE_EN = "Maintenance log and reserve fund study — Quebec Law 16"
SCOPE = [
    "Visite des parties communes et examen des documents disponibles;",
    "Préparation du carnet d’entretien : composantes, entretien et interventions à prévoir;",
    "Étude du fonds de prévoyance sur 25 ans : coûts estimés et contributions recommandées;",
    "Remise des documents et présentation des résultats au conseil d’administration.",
]
SCOPE_EN = [
    "Visit of the common areas and review of available documents;",
    "Maintenance log: components, maintenance and planned interventions;",
    "25-year reserve fund study: estimated costs and recommended contributions;",
    "Delivery of the documents and presentation of the results to the board of directors.",
]
DOCUMENTS = (
    "Documents à demander après acceptation (selon disponibilité) :\n"
    "• Déclaration de copropriété et modifications;\n"
    "• Plans et certificat de localisation;\n"
    "• Carnet d’entretien et étude du fonds existants;\n"
    "• États financiers, budget, solde daté du fonds et contributions prévues;\n"
    "• Rapports, historique des travaux et sinistres, factures importantes;\n"
    "• Contrats d’entretien, garanties et manuels des équipements."
)
DOCUMENTS_EN = (
    "Documents to request after acceptance (if available):\n"
    "• Declaration of co-ownership and amendments;\n"
    "• Plans and certificate of location;\n"
    "• Existing maintenance log and reserve fund study;\n"
    "• Financial statements, budget, dated fund balance and planned contributions;\n"
    "• Reports, major work and loss history, significant invoices;\n"
    "• Maintenance contracts, warranties and equipment manuals."
)
EQUIPMENT = {'elevator': 'Ascenseur', 'parking': 'Stationnement intérieur', 'pool': 'Piscine'}
_ODS = _DEPT = None


def is_loi16(data):
    return data.get('proposal_kind') == 'loi16' and data.get('department') == 'STR'


def english(data):
    return data.get('language') == 'en'


def normalize(data):
    """Fill workflow defaults only; never infer building or contact facts."""
    data.update(proposal_kind='loi16', department='STR', file_code='LOI')
    data.setdefault('date', datetime.now().strftime('%Y-%m-%d'))
    data.setdefault('project_title', TITLE)
    data.setdefault('service', TITLE)
    data.setdefault('service_lines', list(SCOPE))
    data.setdefault('desc', '\n'.join(SCOPE))
    data.update(desc_confirmed=True, special_note_confirmed=True,
                assumption_access=False, assumption_access_confirmed=True,
                assumption_architect=False, assumption_architect_confirmed=True)
    if data.get('addr'):
        data['addr_confirmed'] = True
        if not data.get('name'):
            data['name'] = 'Syndicat de copropriété — ' + data['addr'].split('\n')[0]
    data['property_type'] = 'Copropriété'
    return data


def equipment_prompt(chat_id, data):
    selected = data.get('loi16_equipment', [])
    _ODS.tg(chat_id, '🏢 Ascenseur, stationnement intérieur ou piscine ?', [
        [{'text': ('✅ ' if key in selected else '') + label,
          'callback_data': 'loi16:eq:' + key}] for key, label in EQUIPMENT.items()
    ] + [[{'text': 'Aucun', 'callback_data': 'loi16:eq:none'},
          {'text': 'Terminé', 'callback_data': 'loi16:eq:done'}],
         [{'text': 'À confirmer', 'callback_data': 'loi16:eq:unknown'}]])


def ask(chat_id, uid):
    data = _ODS.user_data.get(str(uid), {})
    if not is_loi16(data):
        return _OLD_ASK(chat_id, uid)
    normalize(data)
    if not data.get('addr'):
        data['waiting_field'] = 'loi16_address'
        _ODS.save_user_data()
        return _ODS.tg(chat_id, '📍 Adresse de l’immeuble ?')
    if not data.get('loi16_counts_confirmed'):
        data['waiting_field'] = 'loi16_counts'
        _ODS.save_user_data()
        return _ODS.tg(chat_id, '🏘️ Combien d’unités et d’étages ?\nEx. : 6 unités, 3 étages',
                       [[{'text': 'À confirmer', 'callback_data': 'loi16:counts:unknown'}]])
    if not data.get('loi16_equipment_confirmed'):
        data['waiting_field'] = 'loi16_equipment'
        _ODS.save_user_data()
        return equipment_prompt(chat_id, data)
    data.pop('waiting_field', None)
    # Commercial approvals remain with the operator, not the client intake.
    if float(data.get('price') or 0) <= 0:
        data['price_confirmed'] = False
        data['waiting_price'] = True
        _ODS.save_user_data()
        return _ODS.tg(chat_id, '💰 Honoraires du forfait Loi 16 avant taxes ?')
    _ODS.save_user_data()
    return _OLD_ASK(chat_id, uid)


def extract(chat_id, uid, text=None, file_ids=None):
    uid = str(uid)
    previous = _ODS.user_data.get(uid, {})
    if not is_loi16(previous):
        return (_OLD_EXTRACT_MANY(chat_id, uid, file_ids) if file_ids is not None
                else _OLD_EXTRACT_TEXT(chat_id, uid, text))
    prompt = (
        'Extract ONLY explicit facts from this Quebec condominium request. Return JSON: '
        '{"syndicate_name":"","client_name":"","phone":"","email":"","address":"",'
        '"units":null,"floors":null,"equipment":null}. '
        'units/floors must be positive integer counts or null. equipment is null if unspecified, '
        'otherwise an array containing elevator, parking (INDOOR only), pool; [] only if their '
        'absence is explicitly stated. If only some equipment is mentioned, return null unless '
        'the presence/absence of all three is known. Do not infer absent facilities. '
        'Use the sender email, not To/Cc or Metra emails. Preserve building address exactly. '
        'Never substitute a management office address for the building. '
        'syndicate_name is the legal syndicate name if given; client_name is the contact. '
    )
    try:
        content = (_ODS._vision_content(_ODS._download_telegram_images(file_ids), prompt)
                   if file_ids is not None else prompt + '\n' + str(text))
        response = _ODS.client.messages.create(model='claude-sonnet-4-6', max_tokens=1000,
                                               messages=[{'role': 'user', 'content': content}])
        info = _ODS._model_json(response)
        data = {k: previous[k] for k in ('language', 'province', 'proposal_kind', 'department') if k in previous}
        data.update(name=str(info.get('syndicate_name') or info.get('client_name') or '').strip(),
                    manager_name=str(info.get('client_name') or '').strip(),
                    phone=str(info.get('phone') or '').strip(), email=str(info.get('email') or '').strip(),
                    addr=str(info.get('address') or '').strip(), price=0)
        for field in ('units', 'floors'):
            value = info.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                data['loi16_' + field] = value
        data['loi16_counts_confirmed'] = bool(data.get('loi16_units') and data.get('loi16_floors'))
        eq = info.get('equipment')
        if isinstance(eq, list) and all(v in EQUIPMENT for v in eq):
            data.update(loi16_equipment=eq, loi16_equipment_confirmed=True)
        _ODS.user_data[uid] = normalize(data)
        _ODS.save_user_data()
        ask(chat_id, uid)
    except Exception:
        _ODS.logger.exception('Loi 16 request extraction failed')
        previous.pop('extracting', None)
        previous['waiting_field'] = 'loi16_intro'
        _ODS.save_user_data()
        _ODS.tg(chat_id, 'Lecture impossible. Collez le message du client ou indiquez l’adresse, les unités et les étages.')


def handle(update):
    cb = update.get('callback_query') or {}
    msg = cb.get('message') or update.get('message') or {}
    actor = cb.get('from') or msg.get('from') or {}
    if actor.get('id') not in _ODS.ALLOWED_USERS:
        return False
    uid, chat_id = str(actor.get('id')), (msg.get('chat') or {}).get('id')
    data = _ODS.user_data.get(uid, {})
    cdata, text = str(cb.get('data') or ''), str(msg.get('text') or '')
    if cdata == 'dept:STR' and data.get('province', 'QC') == 'QC':
        _DEPT.DEPT_BY_UID[uid] = 'STR'
        _ODS.user_data[uid] = {k: data[k] for k in ('language', 'province') if k in data}
        _ODS.user_data[uid].update(department='STR', date=datetime.now().strftime('%Y-%m-%d'))
        _ODS.save_user_data()
        _ODS.tg(chat_id, '🏗️ Type de mandat ?', [
            [{'text': '🏢 Copropriété — Loi 16', 'callback_data': 'loi16:start'}],
            [{'text': '🏗️ Autre mandat de structure', 'callback_data': 'loi16:general'}]])
    elif cdata == 'loi16:general':
        if data.get('department') != 'STR':
            return False
        data.pop('proposal_kind', None)
        data.pop('waiting_field', None)
        _ODS.save_user_data()
        _ODS.tg(chat_id, '📸 Envoyez une photo ou collez le texte/courriel du client.')
    elif cdata == 'loi16:start':
        if data.get('department') != 'STR' or data.get('province', 'QC') != 'QC':
            return False
        normalize(data)
        data['waiting_field'] = 'loi16_intro'
        _ODS.save_user_data()
        _ODS.tg(chat_id, '🏢 Loi 16\nEnvoyez le message/photo du client, ou indiquez simplement l’adresse, le nombre d’unités et d’étages.')
    elif is_loi16(data) and cdata == 'loi16:counts:unknown':
        data['loi16_counts_confirmed'] = True
        data['loi16_counts_unknown'] = True
        ask(chat_id, uid)
    elif is_loi16(data) and cdata.startswith('loi16:eq:'):
        key = cdata.split(':')[-1]
        selected = list(data.get('loi16_equipment', []))
        if key in EQUIPMENT:
            selected.remove(key) if key in selected else selected.append(key)
            data['loi16_equipment'] = selected
            _ODS.save_user_data()
            equipment_prompt(chat_id, data)
        elif key in ('none', 'done', 'unknown'):
            data['loi16_equipment'] = [] if key != 'done' else selected
            data['loi16_equipment_unknown'] = key == 'unknown'
            data['loi16_equipment_confirmed'] = True
            ask(chat_id, uid)
    elif not cb and is_loi16(data) and text and str(data.get('waiting_field') or '').startswith('loi16_'):
        if text.startswith('/') or text in {b.get('text') for row in _ODS.main_menu()['keyboard'] for b in row}:
            return False
        field = data['waiting_field']
        if field == 'loi16_intro':
            _ODS.executor.submit(extract, chat_id, uid, text)
        elif field == 'loi16_address':
            data['addr'] = text.strip()
            ask(chat_id, uid)
        elif field == 'loi16_counts':
            # Explicitly label counts; also accept the advertised short order.
            units = re.search(r'(\d+)\s*(?:unit|logement|condo)', text, re.I)
            floors = re.search(r'(\d+)\s*(?:étage|etage|floor|storey|story)', text, re.I)
            values = re.findall(r'\d+', text)
            if units:
                data['loi16_units'] = int(units[1])
            if floors:
                data['loi16_floors'] = int(floors[1])
            if not units and not floors and len(values) == 2:
                data['loi16_units'], data['loi16_floors'] = map(int, values)
            data['loi16_counts_confirmed'] = bool(data.get('loi16_units', 0) > 0 and data.get('loi16_floors', 0) > 0)
            ask(chat_id, uid)
        else:
            _ODS.tg(chat_id, 'Choisissez les équipements avec les boutons ci-dessus.')
    else:
        return False
    if cb.get('id'):
        try:
            _ODS.req.post(f'https://api.telegram.org/bot{_ODS.BOT_TOKEN}/answerCallbackQuery',
                          json={'callback_query_id': cb['id']}, timeout=3)
        except Exception:
            pass
    return True


def document_sections(data):
    en = english(data)
    eq = data.get('loi16_equipment', [])
    equipment = ('To be confirmed' if en else 'À confirmer') if data.get('loi16_equipment_unknown') else ', '.join(
        {'elevator': 'Elevator', 'parking': 'Indoor parking', 'pool': 'Pool'}[k] if en else EQUIPMENT[k] for k in eq
    ) or ('None' if en else 'Aucun')
    # An absent field in a recovered/older draft is unknown, never "none".
    if not data.get('loi16_equipment_confirmed'):
        equipment = 'To be confirmed' if en else 'À confirmer'
    facts = (f"{data.get('loi16_units') or '?'} " + ('units' if en else 'unités') + ' · ' +
             f"{data.get('loi16_floors') or '?'} " + ('storeys' if en else 'étages') + ' · ' + equipment)
    scope = data.get('service_lines') or SCOPE
    if en and list(scope) == SCOPE:
        scope = SCOPE_EN
    return [
        ('PROPOSAL OF SERVICES' if en else 'PROPOSITION DE SERVICES', TITLE_EN if en else TITLE),
        ('Property' if en else 'Immeuble', str(data.get('addr') or '—') + '\n' + facts),
        ('Included services' if en else 'Notre accompagnement', '\n'.join('• ' + s for s in scope)),
        ('Fees' if en else 'Honoraires', f"{float(data.get('price') or 0):,.2f} $ CAD — " +
         (('Taxes included' if data.get('taxes') == 'Incluses' else 'Plus applicable taxes') if en else 'Taxes : ' + str(data.get('taxes') or 'En sus'))),
        ('Delivery' if en else 'Délai', (f"{data.get('delai') or '—'} business days after the visit and receipt of the required information." if en else
                                       f"{data.get('delai') or '—'} jours ouvrables après la visite et la réception des informations nécessaires.")),
        ('After acceptance' if en else 'Après acceptation',
         'We will send you a short list of documents to provide, if available.' if en else
         'Nous vous transmettrons une courte liste des documents à fournir, selon leur disponibilité.'),
        ('Scope' if en else 'Portée',
         'Examination of visible, accessible components under the syndicate’s responsibility. Specialized investigations and repair design are excluded unless expressly included.' if en else
         'Examen des composantes visibles et accessibles sous la responsabilité du syndicat. Investigations spécialisées et plans de réparation exclus, sauf mention explicite.'),
        ('Terms' if en else 'Modalités',
         'Valid for 30 days. Deposit: 25%. Invoices payable upon receipt; after 30 days: interest of 1.5% per month (19.56% per year). Changes require written agreement. If cancelled, services already performed remain payable.' if en else
         'Offre valable 30 jours. Acompte : 25 %. Factures payables à réception; après 30 jours : intérêts de 1,5 % par mois (19,56 % par année). Modifications par écrit. En cas d’annulation, les services réalisés demeurent payables.'),
    ]


def generate_pdf(data):
    if not is_loi16(data):
        return _OLD_PDF(data)
    en = english(data)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=_ODS.letter, leftMargin=1.8*cm,
                            rightMargin=1.8*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    normal = ParagraphStyle('loi16', fontName='Loi16Regular', fontSize=9.5, leading=13.5, spaceAfter=5)
    heading = ParagraphStyle('loi16_heading', parent=normal, fontName='Loi16Bold', spaceBefore=6,
                             textColor=colors.HexColor('#12324a'))
    title = ParagraphStyle('loi16_title', parent=heading, fontSize=14, leading=18)
    def para(value, style=normal):
        return Paragraph(html.escape(str(value)).replace('\n', '<br/>'), style)
    story = [para(_ODS.DISPLAY_BRAND, title),
             para('info@metraconsultation.ca | (438) 867-4131'),
             para(str(data.get('odsNum') or 'ODS') + ' | ' + str(data.get('date') or '')),
             HRFlowable(width='100%', thickness=2, color=colors.HexColor('#f5a623')),
             Spacer(1, 8), para(data.get('name') or ('Syndicate' if en else 'Syndicat de copropriété'))]
    if data.get('manager_name') and data['manager_name'] != data.get('name'):
        story.append(para(('Attention: ' if en else 'À l’attention de : ') + data['manager_name']))
    contact = ' | '.join(str(data.get(k)) for k in ('email', 'phone') if data.get(k))
    if contact:
        story.append(para(contact))
    for label, value in document_sections(data):
        story += [para(label, heading), para(value)]
    if data.get('special_note'):
        story += [para('Note', heading), para(data['special_note'])]
    story += [Spacer(1, 10), para('Arash Rohani, ing., P.Eng. | Metra Consultation Inc.'),
              para('Authorized representative: __________________  Signature: ______________  Date: __________' if en else
                   'Représentant autorisé : __________________  Signature : ______________  Date : __________')]
    doc.build(story)
    out.seek(0)
    return out


def generate_excel(data):
    if not is_loi16(data):
        return _OLD_EXCEL(data)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'ODS'
    # Preserve archive recovery addresses B7/B8/B9/B10/B12/B47/E47.
    values = {1: _ODS.DISPLAY_BRAND, 2: 'info@metraconsultation.ca | (438) 867-4131',
              4: TITLE_EN if english(data) else TITLE, 7: data.get('name') or '',
              8: 'Adresse : ' + str(data.get('addr') or ''), 9: 'Cell. : ' + str(data.get('phone') or ''),
              10: 'Courriel : ' + str(data.get('email') or ''), 12: data.get('odsNum') or 'ODS'}
    sections = document_sections(data)
    # Keep the visible proposal compact; recovery cells below remain available.
    for row, section in zip((15, 20, 23, 26, 29, 32, 35), sections[1:]):
        label, value = section
        values[row], values[row+1] = label, value
    values[38] = 'Arash Rohani, ing., P.Eng. | Metra Consultation Inc.'
    values[39] = 'Signature : __________________    Date : __________________'
    values[47] = '\n'.join(data.get('service_lines') or SCOPE)
    values[50] = 'Taxes : ' + str(data.get('taxes') or 'En sus')
    values[51] = sections[4][1]
    values[54] = sections[5][1]
    values[56] = data.get('special_note') or ''
    values[59] = 'Arash Rohani, ing., P.Eng.'
    values[60] = 'Metra Consultation Inc.'
    values[62] = 'Signature : __________________    Date : __________________'
    ws.column_dimensions['A'].width = 3
    for col in ('B', 'C', 'D', 'E', 'F'):
        ws.column_dimensions[col].width = 18
    for row, value in values.items():
        ws.cell(row, 2, value)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4 if row == 47 else 6)
        ws.cell(row, 2).alignment = Alignment(wrap_text=True, vertical='top')
        ws.cell(row, 2).font = Font(name='Calibri', size=11, bold=row in (1, 4, 15, 20, 25, 32, 35, 38, 41, 44))
        ws.row_dimensions[row].height = max(18, sum(max(1, (len(s)+85)//86) for s in str(value).split('\n')) * 15)
    ws['E47'] = float(data.get('price') or 0)
    ws['F47'] = '=E47'
    ws['F47'].number_format = '#,##0.00 "CAD"'
    for row in range(1, 63):
        if row not in values:
            ws.row_dimensions[row].height = 4
        if row >= 47:
            ws.row_dimensions[row].hidden = True
    ws.print_area = 'B1:F39'
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    metadata = wb.create_sheet('_loi16')
    metadata['A1'] = json.dumps({k: v for k, v in data.items() if k.startswith('loi16_') or k in
                               ('proposal_kind', 'language', 'province', 'manager_name', 'project_title')}, ensure_ascii=False)
    metadata.sheet_state = 'hidden'
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def show_format(chat_id, data):
    if not is_loi16(data):
        return _OLD_FORMAT(chat_id, data)
    data['odsNum'] = _ODS.build_ods_num(data) + '-' + _ODS.build_short_title(data)
    _ODS.save_user_data()
    _ODS.tg(chat_id, f"✅ Loi 16 — Prêt à générer\n{data.get('name')}\n{data.get('addr')}\n"
            f"{document_sections(data)[1][1].splitlines()[-1]}\n"
            f"💰 {float(data.get('price') or 0):,.2f} $ CAD\n⏱️ {data.get('delai')} jours ouvrables\n{data['odsNum']}", [
        [{'text': '📦 Générer Excel + PDF', 'callback_data': 'both'}],
        [{'text': '✏️ Changer prix', 'callback_data': 'price'},
         {'text': '✏️ Modifier le mandat', 'callback_data': 'desc_custom'}],
        [{'text': '🔄 Nouveau client', 'callback_data': 'nouveau'}]])


def install(ods, departments):
    global _ODS, _DEPT, _OLD_ASK, _OLD_PDF, _OLD_EXCEL, _OLD_FORMAT, _OLD_EXTRACT_TEXT, _OLD_EXTRACT_MANY, _OLD_CREATE
    _ODS, _DEPT = ods, departments
    _OLD_ASK, _OLD_PDF, _OLD_EXCEL = ods.ask_next_missing, ods.generate_pdf, ods.generate_excel
    _OLD_FORMAT = ods.show_format_buttons
    _OLD_EXTRACT_TEXT, _OLD_EXTRACT_MANY = ods.do_extract_text, ods.do_extract_many
    ods.ask_next_missing = ask
    ods.generate_pdf, ods.generate_excel, ods.show_format_buttons = generate_pdf, generate_excel, show_format
    ods.do_extract_text = lambda chat, uid, text: extract(chat, uid, text=text)
    ods.do_extract_many = lambda chat, uid, ids: extract(chat, uid, file_ids=ids)
    _OLD_CREATE = ods._do_create_project
    def create(chat_id, uid, offer_ref=None):
        result = _OLD_CREATE(chat_id, uid, offer_ref)
        record = ods.offers_history.get(str(uid), {}).get(offer_ref, {}) if offer_ref else {}
        data = record.get('data') or ods.user_data.get(str(uid), {})
        if is_loi16(data) and data.get('project_created') and not data.get('loi16_checklist_shown'):
            checklist = DOCUMENTS_EN if english(data) else DOCUMENTS
            if ods.tg(chat_id, checklist):
                data['loi16_checklist_shown'] = True
                ods.save_user_data()
                ods.save_offers_history()
        return result
    ods._do_create_project = create
    ods.logger.warning('LOI16 ACTIVE: Structure subtype, short intake and compact PDF/Excel')
