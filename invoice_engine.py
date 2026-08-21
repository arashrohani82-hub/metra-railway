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
    return f"FAC P{invoice_date.strftime('%y')}-{int(invoice_number):03d}-{invoice_discipline(data)}.pdf"


def _client_name(data):
    civility = str(data.get("civility") or "").strip()
    name = str(data.get("name") or data.get("client_name") or "Client").strip()
    if civility and not name.lower().startswith(civility.lower()):
        return f"{civility} {name}".strip()
    return name


def _service_lines(data):
    lines = data.get("service_lines") or []
    if not lines:
        text = str(data.get("desc") or data.get("service") or "Services professionnels")
        lines = [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]
    return lines[:7]


def _project_reference(data):
    return str(
        data.get("project_folder")
        or data.get("project_code")
        or data.get("odsNum")
        or "À confirmer"
    )


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
        logo = Image(logo_path, width=4.0 * cm, height=1.65 * cm)

    company = Paragraph(
        "<b>Métra Structure Inc. 9527-1532 Québec inc</b><br/>"
        "1280 Rue Saint-Jacques, Québec H3C 0G1, Canada<br/>"
        '<font color="#1155cc"><u>accounting@metrastructure.ca</u></font><br/>'
        '<font color="#1155cc"><u>www.metrastructure.ca</u></font>',
        normal,
    )
    invoice_meta = Table([
        [Paragraph("<b>FACTURE</b>", title)],
        [Paragraph(f"<b>N° facture:</b>&nbsp;&nbsp;&nbsp; {int(invoice_number)}", right)],
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
    sold = Paragraph(f"<b>Vendu à :</b><br/>{client_name}<br/>{address}<br/>{phone}", normal)
    shipped = Paragraph(f"<b>Expédié à :</b><br/>{client_name}<br/>{address}<br/>{phone}", normal)
    story.append(Table([[sold, shipped]], colWidths=[9.2 * cm, 8.7 * cm]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>Projet :</b> {escape(_project_reference(data))}", bold))
    story.append(Spacer(1, 0.22 * cm))

    description = "<br/>".join(
        f"• {escape(str(line).strip().rstrip(';'))};" for line in _service_lines(data)
    )
    quantity = (
        f"{values['percentage']:g}%"
        if values["percentage"] is not None else "Forfait"
    )
    table_data = [
        [
            Paragraph("<b>Quantité</b>", normal),
            Paragraph("<b>Description</b>", normal),
            Paragraph("<b>Taxe</b>", normal),
            Paragraph("<b>Prix unit.</b>", normal),
            Paragraph("<b>Montant</b>", normal),
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
                "Métra Structure Inc. 9527-1532 Québec inc TPS 5% : # 733902225 RT0001<br/>"
                "Métra Structure Inc. 9527-1532 Québec inc TVQ 9.975% : # 1232151826 TQ0001",
                small,
            ),
            "", "", "", "",
        ],
    ]
    services = Table(
        table_data,
        colWidths=[1.9 * cm, 9.8 * cm, 1.05 * cm, 2.65 * cm, 2.6 * cm],
        rowHeights=[0.55 * cm, 5.2 * cm, 0.7 * cm],
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
    story.append(Spacer(1, 0.12 * cm))

    tax_info = Paragraph(
        "<b>Paramètres de taxes</b><br/>"
        "TPS (fédéral)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 5%<br/>"
        "TVQ (Québec)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 9.975%<br/>"
        "Remise (rabais)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 0%",
        normal,
    )
    totals = Table([
        ["Sous-total:", f"{values['subtotal']:,.2f}"],
        ["Rabais:", "0.00"],
        ["Sous-total après rabais:", f"{values['subtotal']:,.2f}"],
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
        f"Conditions : Net 30. Échu&nbsp;&nbsp;&nbsp;&nbsp; {due_date.isoformat()}<br/>"
        "Remarques : Frais 2%, taux d’intérêt mensuel sur factures échues depuis 30 jours.<br/>"
        "Chargé de projets : Arash Rohani",
        normal,
    ))

    doc.build(story)
    return output.getvalue(), values, due_date
