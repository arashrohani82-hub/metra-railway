import io
import logging
import re
import urllib.parse

from pypdf import PdfReader
import requests

import invoice_preview_runtime as preview

app = preview.app
legacy = preview.legacy
runtime = preview.runtime
fixed = runtime.base
logger = logging.getLogger(__name__)


def _project_token(data):
    text = str(data.get('project_folder') or data.get('project_code') or '')
    match = re.search(r'P\d{2}-\d{3}-[A-Z]{2,5}', text, re.I)
    return match.group(0).upper() if match else text.strip().upper()


def _download_onedrive_file(token, owner, relative_path):
    owner_q = urllib.parse.quote(owner, safe='')
    path_q = urllib.parse.quote(relative_path, safe='/')
    response = requests.get(
        f'https://graph.microsoft.com/v1.0/users/{owner_q}/drive/root:/{path_q}:/content',
        headers={'Authorization': f'Bearer {token}'},
        timeout=45,
    )
    if response.status_code != 200:
        raise RuntimeError(f'lecture facture impossible ({response.status_code})')
    return response.content


def _pdf_text(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return '\n'.join((page.extract_text() or '') for page in reader.pages)


def _subtotal_from_text(text):
    # Prefer the first simple "Sous-total:" value, which is the amount before tax.
    match = re.search(
        r'Sous[- ]?total\s*:\s*\$?\s*([0-9][0-9\s,]*[.,][0-9]{2})',
        text,
        re.I,
    )
    if not match:
        return None
    raw = match.group(1).replace(' ', '')
    if ',' in raw and '.' in raw:
        raw = raw.replace(',', '')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        return float(raw)
    except ValueError:
        return None


def project_billed_total(data):
    """Sum issued pre-tax invoice subtotals for the selected project from Financial."""
    token_key = _project_token(data)
    if not token_key:
        return 0.0, []

    token = legacy.graph_access_token()
    owner = legacy.INVOICE_DRIVE_OWNER
    root = legacy.INVOICE_FOLDER
    items = legacy.list_onedrive_children(token, owner, root)
    total = 0.0
    matched = []

    for item in items:
        name = str(item.get('name') or '')
        if not name.lower().endswith('.pdf'):
            continue
        try:
            content = _download_onedrive_file(token, owner, f'{root}/{name}')
            text = _pdf_text(content)
            normalized = re.sub(r'\s+', '', text).upper()
            if re.sub(r'\s+', '', token_key).upper() not in normalized:
                continue
            subtotal = _subtotal_from_text(text)
            if subtotal is None:
                logger.warning('Could not read subtotal from invoice %s', name)
                continue
            total += subtotal
            matched.append({'name': name, 'subtotal': subtotal})
        except Exception as exc:
            logger.warning('Cumulative invoice scan skipped %s: %s', name, exc)

    logger.info(
        'Project cumulative invoicing: project=%s invoices=%s subtotal=%.2f',
        token_key,
        len(matched),
        total,
    )
    return round(total, 2), matched


def _invoice_status(data):
    contract = round(float(data.get('price') or 0), 2)
    billed, invoices = project_billed_total(data)
    remaining = round(contract - billed, 2)
    pct = round((billed / contract * 100.0), 1) if contract > 0 else 0.0
    return {
        'contract': contract,
        'billed': billed,
        'remaining': remaining,
        'percent': pct,
        'invoices': invoices,
    }


def show_invoice_options_control(chat_id, uid):
    uid = str(uid)
    data = legacy.user_data.get(uid, {})
    if not data.get('project_created') or not data.get('project_folder'):
        legacy.tg(chat_id, "⚠️ Sélectionnez d'abord un projet.")
        return

    try:
        status = _invoice_status(data)
    except Exception as exc:
        logger.exception('Unable to calculate cumulative invoicing')
        legacy.tg(chat_id, f"❌ Impossible de vérifier le cumul des factures : {exc}")
        return

    if status['contract'] <= 0:
        legacy.tg(chat_id, "⚠️ Le montant du contrat doit être défini avant la facturation.")
        return

    if status['remaining'] <= 0.01:
        legacy.tg(
            chat_id,
            "✅ Ce projet est déjà facturé à 100 %.\n\n"
            f"Contrat : {status['contract']:,.2f} $\n"
            f"Déjà facturé : {status['billed']:,.2f} $ ({status['percent']:g} %)\n"
            "Reste à facturer : 0.00 $",
        )
        return

    legacy.tg(
        chat_id,
        "🧾 Nouvelle facture\n\n"
        f"Projet : {data.get('project_folder')}\n"
        f"Client : {data.get('name') or 'Non indiqué'}\n\n"
        f"💼 Contrat : {status['contract']:,.2f} $\n"
        f"📤 Déjà facturé : {status['billed']:,.2f} $ ({status['percent']:g} %)\n"
        f"💰 Reste à facturer : {status['remaining']:,.2f} $\n\n"
        "Quel pourcentage du contrat voulez-vous facturer maintenant ?",
        [
            [
                {'text': '25 %', 'callback_data': 'invoice_pct:25'},
                {'text': '50 %', 'callback_data': 'invoice_pct:50'},
            ],
            [
                {'text': '75 %', 'callback_data': 'invoice_pct:75'},
                {'text': '100 %', 'callback_data': 'invoice_pct:100'},
            ],
            [{'text': '📊 Autre pourcentage', 'callback_data': 'invoice_pct_other'}],
            [{'text': '💵 Montant fixe', 'callback_data': 'invoice_fixed'}],
            [{'text': '❌ Annuler', 'callback_data': 'invoice_cancel'}],
        ],
    )


def show_invoice_preview_control(chat_id, uid, percentage=None, fixed_amount=None):
    uid = str(uid)
    data = legacy.user_data.get(uid, {})
    if not data.get('project_folder'):
        legacy.tg(chat_id, "❌ Projet introuvable. Ouvrez de nouveau Facturation.")
        return

    try:
        status = _invoice_status(data)
        values = legacy.invoice_values(
            data.get('price') or 0,
            percentage=percentage,
            fixed_amount=fixed_amount,
        )
        new_subtotal = round(float(values['subtotal']), 2)
        after = round(status['billed'] + new_subtotal, 2)
        remaining_after = round(status['contract'] - after, 2)

        if new_subtotal <= 0:
            legacy.tg(chat_id, "❌ Le montant de cette facture doit être supérieur à 0 $.")
            return

        if after > status['contract'] + 0.01:
            legacy.tg(
                chat_id,
                "⛔ Facturation bloquée : le cumul dépasserait le contrat.\n\n"
                f"Contrat : {status['contract']:,.2f} $\n"
                f"Déjà facturé : {status['billed']:,.2f} $\n"
                f"Nouvelle facture : {new_subtotal:,.2f} $\n"
                f"Cumul demandé : {after:,.2f} $\n"
                f"Maximum encore facturable : {max(status['remaining'], 0):,.2f} $\n\n"
                "Choisissez un pourcentage ou un montant inférieur.",
            )
            return

        # Generate the established PDF preview first.
        preview.show_invoice_preview_pdf(
            chat_id,
            uid,
            percentage=percentage,
            fixed_amount=fixed_amount,
        )

        pct_after = (after / status['contract'] * 100.0) if status['contract'] else 0.0
        legacy.tg(
            chat_id,
            "📊 Contrôle cumulatif du projet\n\n"
            f"Contrat : {status['contract']:,.2f} $\n"
            f"Déjà facturé avant cette facture : {status['billed']:,.2f} $\n"
            f"Cette facture : {new_subtotal:,.2f} $\n"
            f"Cumul après cette facture : {after:,.2f} $ ({pct_after:.1f} %)\n"
            f"Reste après cette facture : {max(remaining_after, 0):,.2f} $",
        )
    except Exception as exc:
        logger.exception('Cumulative invoice preview control failed')
        legacy.tg(chat_id, f"❌ Contrôle cumulatif impossible : {exc}")


# ods_runtime calls fixed.show_invoice_options_multi directly after project selection
# and after entering a contract amount, so replace that function at runtime.
fixed.show_invoice_options_multi = show_invoice_options_control
legacy.show_invoice_options = show_invoice_options_control
legacy.show_invoice_preview = show_invoice_preview_control

logger.info('CUMULATIVE PROJECT INVOICING CONTROL ACTIVE')
