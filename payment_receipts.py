"""Invoice-specific payment acknowledgements, including partial payments."""
import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def money(value):
    try:
        result = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError('Montant invalide') from exc
    if not result.is_finite():
        raise ValueError('Montant invalide')
    return result


def parse_amount(text):
    raw = str(text).strip().replace('$', '').replace(' ', '').replace('\u00a0', '')
    if ',' in raw and '.' in raw:
        raw = raw.replace(',', '')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    return money(raw)


def invoice_details(text, filename):
    match = re.search(r'Montant total\s*:\s*\$?\s*([\d ,]+[.,]\d{2})', text, re.I)
    if not match:
        raise ValueError('Total de facture introuvable : ' + filename)
    total = parse_amount(match.group(1))
    if total <= 0:
        raise ValueError('Total de facture invalide')
    client = re.search(r'Facturé à\s*:\s*\n(.*?)\nProjet\s*:', text, re.S | re.I)
    lines = [s.strip() for s in client.group(1).splitlines() if s.strip()] if client else []
    if not lines:
        raise ValueError('Client de la facture introuvable')
    email = next((s for s in lines if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', s)), '')
    number = re.search(r'N[°o]\s*facture\s*:\s*(\d+)', text, re.I)
    return {'filename': filename, 'number': number.group(1) if number else filename,
            'total': str(total), 'client': lines[0], 'client_lines': lines, 'email': email}


def payment_balance(invoice, records):
    paid = sum((money(r['amount']) for r in records), Decimal('0.00'))
    return paid, money(invoice['total']) - paid


def validate_payment(invoice, records, amount):
    amount = money(amount)
    _, remaining = payment_balance(invoice, records)
    if amount <= 0 or amount > remaining:
        raise ValueError(f'Montant reçu invalide. Solde disponible : {remaining:.2f} $')
    return amount


def receipt_pdf(record):
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, leftMargin=1.7*cm,
                            rightMargin=1.7*cm, topMargin=1.6*cm, bottomMargin=1.6*cm)
    styles = getSampleStyleSheet()
    normal = styles['BodyText']
    normal.fontName = 'Helvetica'
    normal.fontSize = 10
    normal.leading = 14
    title = styles['Heading1']
    title.textColor = colors.HexColor('#223F59')
    def p(text):
        return Paragraph(text, normal)
    invoice = record['invoice']
    remaining = money(record['remaining'])
    status = 'FACTURE ACQUITTÉE' if remaining == 0 else 'PAIEMENT PARTIEL'
    story = [Paragraph('METRA CONSULTATION INC.', styles['Heading2']),
             p('1280, rue Saint-Jacques, Montréal (Québec) H3C 0G1<br/>accounting@metrastructure.ca'),
             Spacer(1, .65*cm), Paragraph('REÇU DE PAIEMENT', title),
             p('Reçu : <b>'+escape(record['id'])+'</b>'),
             p('Date de réception : '+escape(record['date'])), Spacer(1,.5*cm),
             p('<b>Client</b><br/>'+'<br/>'.join(escape(s) for s in invoice['client_lines'])),
             Spacer(1,.35*cm), p('<b>Projet :</b> '+escape(record['project_folder'])),
             p('<b>Facture :</b> '+escape(invoice['filename'])),
             p('<b>Mode de paiement :</b> '+escape(record['method'])), Spacer(1,.55*cm)]
    rows = [['Total de la facture (taxes incluses)', f"{money(invoice['total']):,.2f} $"],
            ['Montant reçu pour ce paiement', f"{money(record['amount']):,.2f} $"],
            ['Cumul des paiements enregistrés', f"{money(record['cumulative']):,.2f} $"],
            ['Solde de la facture', f'{remaining:,.2f} $']]
    table = Table(rows, colWidths=[12*cm,5*cm])
    table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'Helvetica'),
        ('FONTSIZE',(0,0),(-1,-1),10),('ALIGN',(1,0),(1,-1),'RIGHT'),
        ('BOTTOMPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),
        ('BACKGROUND',(0,3),(-1,3),colors.HexColor('#E8EFF5')),
        ('FONTNAME',(0,3),(-1,3),'Helvetica-Bold')]))
    story += [table, Spacer(1,.55*cm), Paragraph(status,styles['Heading2']),
              p('Metra Consultation Inc. confirme avoir reçu le montant indiqué ci-dessus, '
                'imputé exclusivement à la facture identifiée dans ce reçu.'),
              p('Ce reçu confirme ce paiement. Il ne libère pas des montants dus au titre '
                'd’autres factures ou du solde du contrat.'),
              Spacer(1,.45*cm), p('Arash Rohani, ing., P.Eng.<br/>Président - Metra Consultation Inc.')]
    doc.build(story)
    return output.getvalue()
