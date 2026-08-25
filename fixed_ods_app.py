import re
from datetime import datetime

from flask import jsonify

import app as legacy

app = legacy.app
VERSION = 'ods-project-invoicing-v3'


def _first_available(numbers, start=81):
    used = {int(n) for n in numbers}
    candidate = start
    while candidate in used:
        candidate += 1
    return str(candidate).zfill(3)


def get_next_project_num_from_onedrive():
    """Read archived ODS files and return the first unused number without consuming it."""
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


# Keep the safer ODS numbering override.
legacy.get_next_project_num = get_next_project_num_from_onedrive
legacy.logger.info('ODS NUMBERING FIX ACTIVE: %s', VERSION)


# ---------------------------------------------------------------------------
# Reusable project invoicing
# ---------------------------------------------------------------------------

def invoicing_main_menu():
    return {
        'keyboard': [
            [{'text': '📝 Nouvelle offre'}],
            [{'text': '📁 Convertir une offre en projet'}],
            [{'text': '🧾 Facturer un projet'}],
            [{'text': '📷 Envoyer une photo'}, {'text': '📋 Coller un texte'}],
            [{'text': '❓ Aide'}, {'text': '❌ Annuler'}],
        ],
        'resize_keyboard': True,
        'is_persistent': True,
        'input_field_placeholder': 'Photo ou texte du client…',
    }


legacy.main_menu = invoicing_main_menu


def converted_project_records(uid):
    """Return converted projects, newest first, without consuming or changing them."""
    records = legacy.offers_history.get(str(uid), {})
    projects = []
    for ref, record in records.items():
        if not record.get('converted'):
            continue
        data = record.get('data') or {}
        folder = record.get('project_folder') or data.get('project_folder') or ''
        if not folder:
            continue
        projects.append((ref, record))
    return sorted(
        projects,
        key=lambda item: item[1].get('sent_at') or '',
        reverse=True,
    )


def show_projects_for_invoice(chat_id, uid):
    projects = converted_project_records(uid)
    if not projects:
        legacy.tg(
            chat_id,
            "Aucun projet converti n'est disponible pour la facturation.",
        )
        return

    rows = []
    for ref, record in projects[:20]:
        data = record.get('data') or {}
        folder = record.get('project_folder') or data.get('project_folder') or 'Projet'
        client = str(data.get('name') or '').strip()
        label = f"{folder} — {client}" if client else folder
        rows.append([
            {
                'text': label[:60],
                'callback_data': f'project_invoice_pick:{ref}',
            }
        ])

    text = "🧾 Facturer un projet\n\nChoisissez le projet :"
    if len(projects) > 20:
        text += "\n(20 projets les plus récents sont affichés.)"
    legacy.tg(chat_id, text, rows)


def select_project_for_invoice(chat_id, uid, ref):
    uid = str(uid)
    record = legacy.offers_history.get(uid, {}).get(ref)
    if not record or not record.get('converted'):
        legacy.tg(chat_id, "❌ Projet introuvable. Ouvrez de nouveau la liste.")
        return

    data = legacy.history_data_copy(record.get('data') or {})
    data['project_created'] = True
    data['project_folder'] = (
        record.get('project_folder') or data.get('project_folder') or ''
    )
    data['project_web_url'] = (
        record.get('project_web_url') or data.get('project_web_url') or ''
    )
    data['selected_offer_ref'] = ref
    data['pending_invoice'] = None
    data['waiting_invoice_percentage'] = False
    data['waiting_invoice_amount'] = False
    legacy.user_data[uid] = data
    legacy.save_user_data()
    show_invoice_options_multi(chat_id, uid)


def show_invoice_options_multi(chat_id, uid):
    data = legacy.user_data.get(str(uid), {})
    if not data.get('project_created') or not data.get('project_folder'):
        legacy.tg(chat_id, "⚠️ Sélectionnez d'abord un projet converti.")
        return

    history = data.get('invoice_history') or []
    previous = ''
    if history:
        billed_subtotal = sum(float(item.get('subtotal') or 0) for item in history)
        previous = (
            f"\nFactures déjà émises : {len(history)}"
            f"\nSous-total déjà facturé : {billed_subtotal:,.2f} $\n"
        )

    legacy.tg(
        chat_id,
        "🧾 Nouvelle facture\n\n"
        f"Projet : {data.get('project_folder')}\n"
        f"Client : {data.get('name') or 'Non indiqué'}"
        f"{previous}\n"
        "Choisissez le mode de facturation :",
        [
            [{'text': '✅ 25 % du contrat', 'callback_data': 'invoice_pct:25'}],
            [{'text': '📊 Autre pourcentage', 'callback_data': 'invoice_pct_other'}],
            [{'text': '💵 Montant fixe', 'callback_data': 'invoice_fixed'}],
            [{'text': '❌ Plus tard', 'callback_data': 'invoice_cancel'}],
        ],
    )


legacy.show_invoice_options = show_invoice_options_multi


_original_issue_invoice = legacy.do_issue_invoice


def do_issue_invoice_multi(chat_id, uid):
    """Allow repeated invoices while retaining an invoice history for the project."""
    uid = str(uid)
    data = legacy.user_data.get(uid, {})
    old_latest = {
        key: data.get(key)
        for key in (
            'invoice_number', 'invoice_filename', 'invoice_subtotal',
            'invoice_total', 'invoice_due_date', 'invoice_issued_at',
        )
    }
    history = list(data.get('invoice_history') or [])

    # The legacy routine uses invoice_issued_at as a one-time guard. Clear only
    # that guard for a deliberately selected new invoice; the global creation
    # lock still prevents simultaneous duplicate issuance.
    data.pop('invoice_issued_at', None)
    legacy.user_data[uid] = data
    legacy.save_user_data()

    _original_issue_invoice(chat_id, uid)

    updated = legacy.user_data.get(uid, {})
    new_issued_at = updated.get('invoice_issued_at')
    if new_issued_at and new_issued_at != old_latest.get('invoice_issued_at'):
        entry = {
            'number': updated.get('invoice_number'),
            'filename': updated.get('invoice_filename'),
            'subtotal': updated.get('invoice_subtotal'),
            'total': updated.get('invoice_total'),
            'due_date': updated.get('invoice_due_date'),
            'issued_at': new_issued_at,
        }
        # Avoid duplicating the same invoice if Telegram retries a completed update.
        if not any(
            str(item.get('number')) == str(entry.get('number'))
            for item in history
        ):
            history.append(entry)
        updated['invoice_history'] = history
        legacy.user_data[uid] = updated
        legacy.save_user_data()
        legacy.record_sent_offer(uid, updated)
        return

    # If issuance failed, restore the previous latest-invoice marker so project
    # history is not silently damaged.
    for key, value in old_latest.items():
        if value is not None:
            updated[key] = value
    updated['invoice_history'] = history
    legacy.user_data[uid] = updated
    legacy.save_user_data()


legacy.do_issue_invoice = do_issue_invoice_multi


_original_handle_update = legacy.handle_update


def handle_update_with_project_invoicing(data):
    """Intercept only the new project-invoicing actions; delegate everything else."""
    try:
        msg = data.get('message', {})
        cb = data.get('callback_query', {})

        if msg and msg.get('text') == '🧾 Facturer un projet':
            actor_id = msg.get('from', {}).get('id')
            chat_id = msg.get('chat', {}).get('id')
            if actor_id not in legacy.ALLOWED_USERS:
                if chat_id:
                    legacy.tg(chat_id, "⛔ Ce bot est privé.")
                return
            show_projects_for_invoice(chat_id, str(actor_id))
            return

        if cb:
            cdata = cb.get('data', '')
            if cdata.startswith('project_invoice_pick:'):
                actor_id = cb.get('from', {}).get('id')
                chat_id = cb.get('message', {}).get('chat', {}).get('id')
                if actor_id not in legacy.ALLOWED_USERS:
                    if chat_id:
                        legacy.tg(chat_id, "⛔ Ce bot est privé.")
                    return
                try:
                    legacy.req.post(
                        f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                        json={'callback_query_id': cb.get('id')},
                        timeout=3,
                    )
                except Exception:
                    pass
                ref = cdata.split(':', 1)[1]
                select_project_for_invoice(chat_id, str(actor_id), ref)
                return
    except Exception:
        legacy.logger.exception('Project invoicing interceptor failed')

    return _original_handle_update(data)


legacy.handle_update = handle_update_with_project_invoicing
legacy.logger.info('PROJECT INVOICING FLOW ACTIVE: %s', VERSION)


@app.route('/debug/ods-number')
def debug_ods_number():
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
