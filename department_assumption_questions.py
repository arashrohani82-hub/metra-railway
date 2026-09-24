"""Department-specific confirmation questions for ODS assumptions/exclusions.

Structure keeps the legacy two structural questions. Civil and Geotechnical
receive their own button-only confirmation flow, and only confirmed items are
printed under the offer assumptions.
"""

import department_ods_patch as dept

legacy = dept.legacy

QUESTIONS = {
    'CIV': [
        (
            'civ_docs',
            '📐 Ajouter cette hypothèse à l\'offre?\n\n'
            'Les plans, relevés, certificat de localisation et informations disponibles nécessaires au mandat seront fournis par le client avant le début des travaux.',
            'Plans, relevés, certificat de localisation et informations disponibles nécessaires au mandat fournis par le client avant le début des travaux;'
        ),
        (
            'civ_survey',
            '📏 Ajouter cette exclusion à l\'offre?\n\n'
            'Relevé d’arpentage.',
            'Relevé d’arpentage;'
        ),
        (
            'civ_fees',
            '🏛️ Ajouter cette exclusion à l\'offre?\n\n'
            'Les frais de permis, frais municipaux, frais de raccordement et droits exigés par les autorités ne sont pas inclus.',
            'Les frais de permis, frais municipaux, frais de raccordement et droits exigés par les autorités ne sont pas inclus;'
        ),
        (
            'civ_other_studies',
            '🧪 Ajouter cette exclusion à l\'offre?\n\n'
            'Étude géotechnique.',
            'Étude géotechnique;'
        ),
        (
            'civ_landscape',
            '🌿 Ajouter cette exclusion à l\'offre?\n\n'
            'Plans d’aménagement paysager.',
            'Plans d’aménagement paysager;'
        ),
        (
            'civ_supervision',
            '👷 Ajouter cette exclusion à l\'offre?\n\n'
            'Surveillance de chantier.',
            'Surveillance de chantier;'
        ),
        (
            'civ_authority_changes',
            '🏙️ Ajouter cette condition à l\'offre?\n\n'
            'Toute exigence additionnelle formulée par la municipalité ou une autre autorité après la préparation des documents pourra nécessiter une révision du mandat.',
            'Toute exigence additionnelle formulée par la municipalité ou une autre autorité après la préparation des documents pourra nécessiter une révision du mandat.'
        ),
    ],
    'GEO': [
        (
            'geo_access',
            '🚜 Ajouter cette hypothèse à l\'offre?\n\n'
            'Le site devra être accessible de façon sécuritaire à l\'équipement requis pour les travaux de terrain et de forage.',
            'Le site devra être accessible de façon sécuritaire à l’équipement requis pour les travaux de terrain et de forage;'
        ),
        (
            'geo_utilities',
            '⚠️ Ajouter cette condition à l\'offre?\n\n'
            'Les services souterrains connus devront être localisés avant le début des forages.',
            'Les services souterrains connus devront être localisés avant le début des forages;'
        ),
        (
            'geo_additional',
            '🕳️ Ajouter cette condition à l\'offre?\n\n'
            'Le nombre et la profondeur des forages sont basés sur les informations disponibles; toute investigation additionnelle rendue nécessaire par les conditions rencontrées devra être autorisée par le client.',
            'Le nombre et la profondeur des forages indiqués dans l’offre sont basés sur les informations disponibles; toute investigation additionnelle rendue nécessaire par les conditions rencontrées devra être autorisée par le client;'
        ),
        (
            'geo_lab',
            '🧫 Ajouter cette exclusion à l\'offre?\n\n'
            'Les essais de laboratoire inclus sont uniquement ceux explicitement indiqués dans la description des services.',
            'Les essais de laboratoire inclus sont uniquement ceux explicitement indiqués dans la description des services;'
        ),
        (
            'geo_environment',
            '🌱 Ajouter cette exclusion à l\'offre?\n\n'
            'La caractérisation environnementale des sols, la recherche de contaminants et les analyses environnementales sont exclues, sauf indication contraire.',
            'La caractérisation environnementale des sols, la recherche de contaminants et les analyses environnementales sont exclues, sauf indication contraire;'
        ),
        (
            'geo_restoration',
            '🛠️ Ajouter cette exclusion à l\'offre?\n\n'
            'La remise en état complète des surfaces, aménagements paysagers ou pavages après les travaux de forage n\'est pas incluse, sauf indication contraire.',
            'La remise en état complète des surfaces, aménagements paysagers ou pavages après les travaux de forage n’est pas incluse, sauf indication contraire.'
        ),
    ],
}

CIVIL_EXCLUSION_KEYS = {
    'civ_survey', 'civ_fees', 'civ_other_studies',
    'civ_landscape', 'civ_supervision',
}

_ORIGINAL_ASK_NEXT_MISSING = legacy.ask_next_missing
_ORIGINAL_SELECTED_ASSUMPTIONS = legacy.selected_assumptions
_ORIGINAL_SHOW_FORMAT_BUTTONS = legacy.show_format_buttons
_ORIGINAL_HANDLE_UPDATE = dept.handle_update


def _code(data, uid=None):
    return dept._dept(data, uid)


def _question_field(key):
    return f'dept_assumption_{key}'


def _confirmed_field(key):
    return f'dept_assumption_{key}_confirmed'


def ask_next_missing(chat_id, uid):
    uid = str(uid)
    data = legacy.user_data.get(uid, {})
    code = _code(data, uid)
    if code not in QUESTIONS:
        return _ORIGINAL_ASK_NEXT_MISSING(chat_id, uid)

    # Let the legacy flow complete all common questions through the special note.
    if not data.get('special_note_confirmed'):
        return _ORIGINAL_ASK_NEXT_MISSING(chat_id, uid)

    for key, prompt, _text in QUESTIONS[code]:
        if not data.get(_confirmed_field(key)):
            legacy.tg(
                chat_id,
                prompt,
                [[
                    {'text': '✅ Oui, ajouter', 'callback_data': f'deptassume:{key}:yes'},
                    {'text': '❌ Non', 'callback_data': f'deptassume:{key}:no'},
                ]],
            )
            return

    # Skip the legacy structural-only confirmations for CIV/GEO.
    data['assumption_access'] = False
    data['assumption_access_confirmed'] = True
    data['assumption_architect'] = False
    data['assumption_architect_confirmed'] = True
    legacy.user_data[uid] = data
    legacy.save_user_data()
    return _ORIGINAL_ASK_NEXT_MISSING(chat_id, uid)


legacy.ask_next_missing = ask_next_missing


def selected_assumptions(data):
    code = _code(data)
    if code not in QUESTIONS:
        return _ORIGINAL_SELECTED_ASSUMPTIONS(data)
    selected = []
    for key, _prompt, text in QUESTIONS[code]:
        if code == 'CIV' and key in CIVIL_EXCLUSION_KEYS:
            continue
        if data.get(_question_field(key)):
            selected.append(text)
    return [f'{i}- {text}' for i, text in enumerate(selected, 1)]


legacy.selected_assumptions = selected_assumptions


def selected_exclusions(data):
    """Print civil exclusions only after explicit confirmation in this offer."""
    if _code(data) != 'CIV':
        return []
    return [text for key, _prompt, text in QUESTIONS['CIV']
            if key in CIVIL_EXCLUSION_KEYS
            and data.get(_confirmed_field(key))
            and data.get(_question_field(key))]


legacy.selected_exclusions = selected_exclusions


def show_format_buttons(chat_id, data):
    code = _code(data)
    if code not in QUESTIONS:
        return _ORIGINAL_SHOW_FORMAT_BUTTONS(chat_id, data)
    try:
        price = data.get('price', 0)
        ods = legacy.build_ods_num(data) + '-' + legacy.build_short_title(data)
        data['odsNum'] = ods
        legacy.save_user_data()
    except Exception:
        price = data.get('price', 0)
        ods = data.get('odsNum', 'ODS')

    selected_count = sum(1 for key, _p, _t in QUESTIONS[code]
                         if data.get(_question_field(key)) and key not in CIVIL_EXCLUSION_KEYS)
    label = 'Civil' if code == 'CIV' else 'Géotechnique'
    lines = [
        '✅ *Prêt à générer*', '',
        '👤 ' + legacy.client_identity(data),
        '📍 ' + legacy.client_contact_fields(data)['address'],
        '📞 ' + legacy.client_contact_fields(data)['phone'],
        '📧 ' + legacy.client_contact_fields(data)['email'],
        '🏠 ' + (data.get('property_type') or '—'),
        '⏱️ ' + (data.get('delai') or '—'),
        '🧾 Taxes : ' + (data.get('taxes') or '—'),
        '📝 Note : ' + (data.get('special_note') or 'Aucune'),
        f'📌 Conditions {label} retenues : {selected_count}',
        *([f'🚫 Exclusions retenues : {len(selected_exclusions(data))}'] if code == 'CIV' else []),
        '',
        '🔧 ' + (data.get('project_title') or data.get('service') or '—'),
        '💰 $' + '{:,}'.format(price) + ' CAD',
        '📄 ' + ods,
        '',
        'Tous les éléments sont confirmés. Générer les fichiers?',
    ]
    legacy.tg(chat_id, '\n'.join(lines), [
        [{'text': '📦 Générer Excel + PDF', 'callback_data': 'both'}],
        [{'text': '✏️ Changer prix', 'callback_data': 'price'}],
        [{'text': '🔄 Nouveau client', 'callback_data': 'nouveau'}],
    ])


legacy.show_format_buttons = show_format_buttons


def handle_update(update):
    callback = (update or {}).get('callback_query') or {}
    cdata = str(callback.get('data') or '')
    if cdata.startswith('deptassume:'):
        parts = cdata.split(':', 2)
        if len(parts) == 3:
            key, answer = parts[1], parts[2]
            message = callback.get('message') or {}
            chat_id = (message.get('chat') or {}).get('id')
            user = callback.get('from') or {}
            uid = str(user.get('id') or chat_id)
            data = legacy.user_data.get(uid, {})
            code = _code(data, uid)
            valid_keys = {item[0] for item in QUESTIONS.get(code, [])}
            if key in valid_keys:
                data[_question_field(key)] = answer == 'yes'
                data[_confirmed_field(key)] = True
                legacy.user_data[uid] = data
                legacy.save_user_data()
                if callback.get('id'):
                    try:
                        legacy.req.post(
                            f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                            json={'callback_query_id': callback['id']}, timeout=10,
                        )
                    except Exception:
                        pass
                ask_next_missing(chat_id, uid)
                return
    return _ORIGINAL_HANDLE_UPDATE(update)


dept.handle_update = handle_update
legacy.logger.warning('DEPARTMENT ASSUMPTION QUESTIONS ACTIVE: CIV/GEO button-only confirmation flow')
