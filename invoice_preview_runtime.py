import io
import logging
from datetime import datetime

import ods_runtime as runtime

app = runtime.app
legacy = runtime.legacy
logger = logging.getLogger(__name__)

# Exact invoice archive requested by management. Keep both preview numbering and
# final issuance on the same OneDrive folder so the proposed and issued numbers
# come from the same source of truth.
legacy.INVOICE_FOLDER = (
    f"Metra Structure Inc/Financial/Facture/{datetime.now().strftime('%Y')}"
)

_original_next_invoice_number = legacy.next_invoice_number


def financial_invoice_items(max_depth=2):
    """Collect invoice files from the configured invoice archive folder."""
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
    logger.info(
        "Invoice archive scan: root=%s items=%s folders=%s",
        root,
        len(collected),
        len(visited),
    )
    return collected


def next_invoice_number_financial(_items=None, year=None):
    """Use the configured invoice archive as source of truth for numbering."""
    try:
        items = financial_invoice_items()
        number = _original_next_invoice_number(items, year=year)
        logger.info("Next invoice number from invoice archive: %s", number)
        return number
    except Exception:
        logger.exception("Invoice numbering failed; using supplied items")
        return _original_next_invoice_number(_items or [], year=year)


legacy.next_invoice_number = next_invoice_number_financial


def _invoice_department(data):
    """Return a safe French department phrase without relying on the random 3-letter code."""
    text = " ".join([
        str(data.get('project_title') or ''),
        str(data.get('service') or ''),
        str(data.get('desc') or ''),
        str(data.get('project_folder') or ''),
    ]).lower()

    civil_terms = (
        'civil', 'drainage', 'stormwater', 'pluvial', 'nivellement', 'grading',
        'raccordement', 'aqueduc', 'égout', 'egout', 'voirie', 'site development',
        'utility', 'municipal',
    )
    geotech_terms = (
        'géotech', 'geotech', 'forage', 'borehole', 'test pit', 'sol ', 'soil ',
        'capacité portante du sol', 'settlement', 'tassement',
    )
    structural_terms = (
        'structur', 'mur porteur', 'poutre', 'charpente', 'fondation', 'seismic',
        'sismique', 'lintel', 'colonne',
    )

    if any(term in text for term in civil_terms):
        return 'notre département de génie civil'
    if any(term in text for term in geotech_terms):
        return 'notre département de géotechnique'
    if any(term in text for term in structural_terms):
        return 'notre département de structure'
    return "nos services d’ingénierie"


def invoice_email_html_standard(data, invoice_number, total, due_date):
    """Standard Metra invoice email including all approved payment methods."""
    project = legacy.html.escape(
        str(data.get('project_folder') or data.get('odsNum') or 'votre projet')
    )
    department = legacy.html.escape(_invoice_department(data))

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;line-height:1.45;color:#1f1f1f">
      <p>Bonjour,</p>

      <p>Veuillez trouver ci-joint la facture N° {int(invoice_number):03d} correspondant aux services que nous vous avons fournis récemment par {department} concernant le projet :</p>

      <p><strong>{project}</strong></p>

      <p>Nous vous remercions pour votre confiance et espérons que nos services ont pleinement répondu à vos attentes.</p>

      <p><strong>Méthodes de paiement :</strong><br>
      Pour régler cette facture, vous pouvez choisir l’une des méthodes de paiement suivantes :</p>

      <p><strong>Paiement par virement Interac (dépôt automatique) :</strong><br>
      Tous les paiements effectués via Interac doivent être envoyés exclusivement à l’adresse courriel suivante :<br>
      <a href="mailto:accounting@metrastructure.ca">accounting@metrastructure.ca</a><br>
      Les paiements sont déposés automatiquement — aucune question de sécurité n’est requise.<br>
      Veuillez noter qu’aucun paiement envoyé à une autre adresse ne sera pris en compte.</p>

      <p><strong>Paiement par transfert bancaire :</strong><br>
      Titulaire du compte : 9325-1532 QUEBEC INC.<br>
      Transit : 00001<br>
      Institution : 003<br>
      Compte : 1099852<br>
      Veuillez nous faire parvenir la confirmation de paiement par courriel à :
      <a href="mailto:accounting@metrastructure.ca">accounting@metrastructure.ca</a></p>

      <p><strong>Paiement par chèque :</strong><br>
      Veuillez faire parvenir votre chèque à nos bureaux à l’adresse suivante :<br>
      Libellé au nom de : 9325-1532 QUEBEC INC.<br>
      1280 Rue Saint-Jacques<br>
      Montréal, QC<br>
      H3C 0G1</p>

      <p>Merci de votre collaboration.</p>

      <p>Cordialement,<br>
      <strong>Service de comptabilité</strong><br>
      Métra Structure Inc.<br>
      <a href="mailto:accounting@metrastructure.ca">accounting@metrastructure.ca</a></p>
    </div>
    """


# send_invoice_email() in app.py resolves this function from the legacy module at
# call time, so overriding it here changes both preview-confirmed and future
# invoice emails without touching the stable issuance flow.
legacy.invoice_email_html = invoice_email_html_standard


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
logger.info(
    'INVOICE PDF PREVIEW FLOW ACTIVE — ARCHIVE=%s — STANDARD PAYMENT EMAIL ACTIVE',
    legacy.INVOICE_FOLDER,
)
