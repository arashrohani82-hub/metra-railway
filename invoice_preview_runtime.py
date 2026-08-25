import io
import logging

import ods_runtime as runtime

app = runtime.app
legacy = runtime.legacy
logger = logging.getLogger(__name__)


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

        # Read the currently available invoice number for the draft only.
        # Nothing is uploaded or reserved at this stage; issuance re-checks it.
        token = legacy.graph_access_token()
        items = legacy.list_onedrive_children(
            token,
            legacy.INVOICE_DRIVE_OWNER,
            legacy.INVOICE_FOLDER,
        )
        preview_number = legacy.next_invoice_number(items)

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
            "🧾 Aperçu PDF — aucune facture n'a encore été envoyée.",
        )

        quantity = (
            f"{float(percentage):g} % du contrat"
            if percentage is not None else "Montant fixe"
        )
        legacy.tg(
            chat_id,
            "✅ Vérifiez le PDF ci-dessus.\n\n"
            f"Projet : {data.get('project_folder')}\n"
            f"Méthode : {quantity}\n"
            f"Sous-total : {values['subtotal']:,.2f} $\n"
            f"TPS : {values['gst']:,.2f} $\n"
            f"TVQ : {values['qst']:,.2f} $\n"
            f"Total : {values['total']:,.2f} $\n\n"
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
logger.info('INVOICE PDF PREVIEW FLOW ACTIVE')
