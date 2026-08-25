import io
import logging

import ods_runtime as runtime

app = runtime.app
legacy = runtime.legacy
logger = logging.getLogger(__name__)

_original_next_invoice_number = legacy.next_invoice_number


def financial_invoice_items(max_depth=2):
    """Collect invoice files from Financial and its immediate subfolders."""
    token = legacy.graph_access_token()
    owner = legacy.INVOICE_DRIVE_OWNER
    root = legacy.INVOICE_FOLDER
    collected = []
    queue = [(root, 0)]
    visited = set()

    while queue:
        path, depth = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        try:
            children = legacy.list_onedrive_children(token, owner, path)
        except Exception as exc:
            logger.warning("Unable to scan invoice folder %s: %s", path, exc)
            continue
        for item in children:
            collected.append(item)
            if depth < max_depth and item.get('folder') is not None:
                name = str(item.get('name') or '').strip()
                if name:
                    queue.append((f"{path}/{name}", depth + 1))
    logger.info("Financial invoice scan: %s items across %s folders", len(collected), len(visited))
    return collected


def next_invoice_number_financial(_items=None, year=None):
    """Use the whole Financial tree as source of truth for the next invoice number."""
    try:
        items = financial_invoice_items()
        number = _original_next_invoice_number(items, year=year)
        logger.info("Next invoice number from Financial tree: %s", number)
        return number
    except Exception:
        logger.exception("Financial invoice numbering failed; using supplied items")
        return _original_next_invoice_number(_items or [], year=year)


legacy.next_invoice_number = next_invoice_number_financial


def show_invoice_preview_pdf(chat_id, uid, percentage=None, fixed_amount=None):
    """Generate and send a real invoice PDF preview without saving or emailing it."""
    uid = str(uid)
    data = legacy.user_data.get(uid, {})
    if not data.get('project_folder'):
        legacy.tg(chat_id, "❌ Projet introuvable. Ouvrez de nouveau Facturation.")
        return

    try:
        values = legacy.invoice_values(data.get('price') or 0, percentage, fixed_amount)
        data['pending_invoice'] = {
            'percentage': percentage,
            'fixed_amount': fixed_amount,
        }
        legacy.user_data[uid] = data
        legacy.save_user_data()

        preview_number = next_invoice_number_financial()
        pdf_bytes, values, due_date = legacy.generate_invoice_pdf(
            data,
            preview_number,
            percentage=percentage,
            fixed_amount=fixed_amount,
            logo_path=legacy.LOGOS['metra'],
        )

        draft_name = f"PREVIEW-{legacy.invoice_filename(preview_number, data)}"
        buffer = io.BytesIO(pdf_bytes)
        buffer.seek(0)
        legacy.tg_doc(
            chat_id,
            buffer,
            draft_name,
            f"🧾 Aperçu PDF — numéro proposé {int(preview_number):03d}. Rien n'a encore été envoyé.",
        )

        quantity = (
            f"{float(percentage):g} % du contrat"
            if percentage is not None else "Montant fixe"
        )
        missing = []
        if not str(data.get('name') or '').strip():
            missing.append('nom du client')
        if not str(data.get('email') or '').strip():
            missing.append('courriel du client')
        if not str(data.get('addr') or data.get('address') or '').strip():
            missing.append('adresse')
        warning = ''
        if missing:
            warning = "\n\n⚠️ À compléter avant l’envoi : " + ", ".join(missing) + "."

        legacy.tg(
            chat_id,
            "✅ Vérifiez le PDF ci-dessus.\n\n"
            f"Projet : {data.get('project_folder')}\n"
            f"Client : {data.get('name') or 'À compléter'}\n"
            f"Méthode : {quantity}\n"
            f"Sous-total : {values['subtotal']:,.2f} $\n"
            f"TPS : {values['gst']:,.2f} $\n"
            f"TVQ : {values['qst']:,.2f} $\n"
            f"Total : {values['total']:,.2f} $"
            f"{warning}\n\n"
            "Si tout est correct, confirmez l'envoi. Le numéro sera revérifié au moment de l'émission.",
            [
                [{'text': '✅ Confirmer et envoyer', 'callback_data': 'invoice_confirm'}],
                [{'text': '✏️ Modifier', 'callback_data': 'invoice_start'}],
                [{'text': '❌ Annuler', 'callback_data': 'invoice_cancel'}],
            ],
        )
    except Exception as exc:
        logger.exception('Invoice PDF preview failed')
        legacy.tg(chat_id, f"❌ Impossible de générer l'aperçu PDF : {exc}")


legacy.show_invoice_preview = show_invoice_preview_pdf
logger.info('INVOICE PDF PREVIEW FLOW ACTIVE — FINANCIAL TREE NUMBERING')
