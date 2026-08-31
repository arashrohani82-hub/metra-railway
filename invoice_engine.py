import io
import os
import re
from datetime import date, timedelta
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, Image as DrawingImage, Rect, String


GST_RATE = 0.05
QST_RATE = 0.09975


def invoice_values(contract_value, percentage=None, fixed_amount=None):
    contract = round(float(contract_value), 2)
    if fixed_amount is not None:
        subtotal = round(float(fixed_amount), 2)
        quantity = None
    else:
        percentage = float(percentage or 25)
        subtotal = round(contract * percentage / 100, 2)
        quantity = percentage
    gst = round(subtotal * GST_RATE, 2)
    qst = round(subtotal * QST_RATE, 2)
    total = round(subtotal + gst + qst, 2)
    return {
        "contract": contract,
        "percentage": quantity,
        "subtotal": subtotal,
        "gst": gst,
        "qst": qst,
        "total": total,
    }


def invoice_discipline(data):
    folder = str(data.get("project_folder") or "")
    match = re.search(r"^P\d{2}-\d{3}-([A-Z]{2,5})(?:-|$)", folder, re.I)
    if match:
        return match.group(1).upper()
    ods = str(data.get("odsNum") or "")
    match = re.search(r"ODS\d{2}-\d{3}-([A-Z]{2,5})(?:-|$)", ods, re.I)
    return match.group(1).upper() if match else "PRJ"


def invoice_filename(invoice_number, data, invoice_date=None):
    invoice_date = invoice_date or date.today()
    folder = str(data.get("project_folder") or "").strip()
    match = re.search(r"^(P\d{2}-\d{3}(?:-[A-Z0-9]{2,5})?)(?:-|$)", folder, re.I)
    project = match.group(1).upper() if match else "PROJET"
    return f"FAC{invoice_date.strftime('%y')}-{int(invoice_number):03d}_{project}.pdf"


def _client_name(data):
    civility = str(data.get("civility") or "").strip()
    name = str(data.get("name") or data.get("client_name") or "Client").strip()
    if civility and civility not in ("M./Mme", "M./Mme.") and not name.lower().startswith(civility.lower()):
        return f"{civility} {name}".strip()
    return name


def _service_lines(data):
    lines = data.get("service_lines") or []
    if isinstance(lines, str):
        lines = [part for part in lines.splitlines() if part.strip()]
    if not lines:
        title = str(data.get("project_title") or "").strip()
        service = str(data.get("service") or "").strip()
        desc = str(data.get("desc") or "").strip()
        if title:
            lines = [title]
        elif service:
            lines = [service]
        elif desc:
            lines = [part.strip() for part in re.split(r"[;\n]+", desc) if part.strip()]
        else:
            lines = ["Services d’ingénierie professionnels"]
    cleaned = []
    for line in lines:
        compact = re.sub(r"\s+", " ", str(line)).strip(" •;.")
        ellipsis = re.search(r"(?:\.{3,}|…)", compact)
        if ellipsis:
            compact = compact[:ellipsis.start()].rstrip(" ,;:–-")
            if "," in compact:
                prefix, fragment = compact.rsplit(",", 1)
                if re.match(
                    r"^(?:incluant|notamment|comprenant|y compris|ainsi que|et\b|ou\b|quant à|relatif|relative|concernant)",
                    fragment.strip().lower(),
                ):
                    compact = prefix.rstrip(" ,;:–-")
        if not compact:
            continue
        cleaned.append(compact)
    return cleaned[:5]


def _project_reference(data):
    return str(
        data.get("project_folder")
        or data.get("project_code")
        or data.get("odsNum")
        or "À confirmer"
    )


def _invoice_description(data, values):
    scope = "<br/>".join(
        f"• {escape(str(line).strip().rstrip(';'))};" for line in _service_lines(data)
    )
    if values["percentage"] is not None:
        billing = (
            f"<b>Facturation : {values['percentage']:g} % du contrat de "
            f"{values['contract']:,.2f} $</b>"
        )
    else:
        billing = "<b>Facturation : montant fixe</b>"
    return billing + "<br/><br/>" + scope


def generate_invoice_pdf(data, invoice_number, percentage=None, fixed_amount=None,
                         logo_path="logo_metra.png", invoice_date=None):
    invoice_date = invoice_date or date.today()
    due_date = invoice_date + timedelta(days=30)
    values = invoice_values(data.get("price") or 0, percentage, fixed_amount)
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        leftMargin=1.25 * cm,
        rightMargin=1.25 * cm,
        topMargin=1.1 * cm,
        bottomMargin=1.1 * cm,
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "InvoiceNormal", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9.2, leading=11.2,
    )
    small = ParagraphStyle(
        "InvoiceSmall", parent=normal, fontSize=7.6, leading=9,
    )
    bold = ParagraphStyle(
        "InvoiceBold", parent=normal, fontName="Helvetica-Bold",
    )
    right = ParagraphStyle(
        "InvoiceRight", parent=normal, alignment=TA_RIGHT,
    )
    title = ParagraphStyle(
        "InvoiceTitle", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=17, leading=19, alignment=TA_RIGHT,
    )

    logo = ""
    if logo_path and os.path.exists(logo_path):
        logo = Drawing(4.0 * cm, 1.45 * cm)
        logo.add(DrawingImage(0, 0, 4.0 * cm, 1.45 * cm, logo_path))

    company = Paragraph(
        "<b>Metra Consultation Inc.</b><br/>"
        "1280, rue Saint-Jacques, Montréal (Québec) H3C 0G1<br/>"
        '<font color="#1155cc"><u>accounting@metrastructure.ca</u></font><br/>'
        '<font color="#1155cc"><u>www.metrastructure.ca</u></font>',
        normal,
    )
    invoice_meta = Table([
        [Paragraph("<b>FACTURE</b>", title)],
        [Paragraph(f"<b>N° facture:</b>&nbsp;&nbsp;&nbsp; {int(invoice_number):03d}", right)],
        [Paragraph(f"<b>Date:</b>&nbsp;&nbsp;&nbsp; {invoice_date.isoformat()}", right)],
        [Paragraph("<b>Page:</b>&nbsp;&nbsp;&nbsp; 1", right)],
    ], colWidths=[5.1 * cm])
    invoice_meta.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    header = Table(
        [[logo, company, invoice_meta]],
        colWidths=[4.5 * cm, 8.3 * cm, 5.1 * cm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story = [header, Spacer(1, 0.55 * cm)]

    client_name = escape(_client_name(data))
    address = escape(str(data.get("addr") or data.get("address") or "À confirmer")).replace("\n", "<br/>")
    phone = escape(str(data.get("phone") or "À compléter"))
    email = escape(str(data.get("email") or "À compléter"))
    sold = Paragraph(
        f"<b>Facturé à :</b><br/>{client_name}<br/>{address}<br/>{phone}<br/>{email}",
        normal,
    )
    project_address = escape(str(data.get("project_address") or data.get("addr") or data.get("address") or "À confirmer")).replace("\n", "<br/>")
    project_box = Paragraph(
        f"<b>Projet :</b><br/>{escape(_project_reference(data))}<br/>{project_address}",
        normal,
    )
    story.append(Table([[sold, project_box]], colWidths=[9.2 * cm, 8.7 * cm]))
    story.append(Spacer(1, 0.35 * cm))

    description = _invoice_description(data, values)
    quantity = (
        f"{values['percentage']:g}%"
        if values["percentage"] is not None else "Forfait"
    )
    unit_price_label = "Valeur contrat" if values["percentage"] is not None else "Montant"
    table_data = [
        [
            Paragraph("<b>Quantité</b>", normal),
            Paragraph("<b>Description</b>", normal),
            Paragraph("<b>Taxe</b>", normal),
            Paragraph(f"<b>{unit_price_label}</b>", normal),
            Paragraph("<b>Montant facturé</b>", normal),
        ],
        [
            Paragraph(quantity, normal),
            Paragraph(description, normal),
            Paragraph("GQ", normal),
            Paragraph(f"$ {values['contract']:,.2f}", right),
            Paragraph(f"$ {values['subtotal']:,.2f}", right),
        ],
        [
            Paragraph(
                "TPS 5% : # 733902225 RT0001 &nbsp;&nbsp;&nbsp; | &nbsp;&nbsp;&nbsp; "
                "TVQ 9.975% : # 1232151826 TQ0001",
                small,
            ),
            "", "", "", "",
        ],
    ]
    invoice_lines = _service_lines(data)
    estimated_text_lines = sum(
        max(1, (len(str(line)) + 54) // 55) for line in invoice_lines
    )
    service_row_height = max(4.7, min(8.2, 1.1 + 0.5 * estimated_text_lines)) * cm
    services = Table(
        table_data,
        colWidths=[1.9 * cm, 9.55 * cm, 1.05 * cm, 2.75 * cm, 2.75 * cm],
        rowHeights=[0.62 * cm, service_row_height, 0.62 * cm],
    )
    services.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B4CAE2")),
        ("GRID", (0, 0), (-1, -1), 0.65, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("SPAN", (0, 2), (-1, 2)),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(services)
    story.append(Spacer(1, 0.15 * cm))

    tax_info = Paragraph(
        "<b>Taxes</b><br/>"
        "TPS (fédéral)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 5%<br/>"
        "TVQ (Québec)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 9.975%",
        normal,
    )
    totals = Table([
        ["Sous-total:", f"{values['subtotal']:,.2f}"],
        ["TPS 5%:", f"{values['gst']:,.2f}"],
        ["TVQ 9.975%:", f"{values['qst']:,.2f}"],
        [Paragraph("<b>Montant total:</b>", right), Paragraph(f"<b>{values['total']:,.2f}</b>", right)],
        ["Montant payé:", "0.00"],
        [Paragraph("<b>Montant dû:</b>", right), Paragraph(f"<b>{values['total']:,.2f}</b>", right)],
    ], colWidths=[4.4 * cm, 2.4 * cm])
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    summary_table = Table([[tax_info, totals]], colWidths=[11.1 * cm, 6.8 * cm])
    summary_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(summary_table)
    story.append(Spacer(1, 0.35 * cm))
    story.append(Paragraph(
        f"Conditions : Net 30 — échéance : {due_date.isoformat()}<br/>"
        "Remarques : intérêts de 2 % par mois sur les factures échues depuis 30 jours.<br/>"
        "Chargé de projet : Arash Rohani, ing., P.Eng.",
        normal,
    ))

    doc.build(story)
    return output.getvalue(), values, due_date
