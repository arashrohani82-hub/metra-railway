import urllib.parse
import re
import os, json, io, shutil, base64, logging
from datetime import datetime
from flask import Flask, request, jsonify, send_file, Response
import anthropic
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak, BaseDocTemplate, PageTemplate, Frame
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
import openpyxl
import random
import requests as req
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=10)

ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

W, H = letter
BLACK = colors.black
BASE = os.path.dirname(os.path.abspath(__file__))

LOGOS = {
    'metra': os.path.join(BASE, 'logo_metra.png'),
    'ing':   os.path.join(BASE, 'logo_ing.png'),
    'peo':   os.path.join(BASE, 'logo_peo.png'),
    'rgcq':  os.path.join(BASE, 'logo_rgcq.png'),
}

PRICES = {
    'Analyse structurale générale': 3500,
    'Inspection et rapport structural': 2800,
    "Avis d'expert — stabilisation et renforcement": 3200,
    'Enlèvement de mur porteur': 3800,
    'Inspection des fondations': 2500,
    'Évaluation des fissures et désordres structuraux': 2200,
    'Mur de soutènement': 4200,
    'Conception structurale complète': 6500,
    'Analyse structurale — sous-sol et ajout au-dessus du garage': 4500,
    'Réaménagement intérieur avec modification structurale': 3500,
}

user_data = {}

# ── Persistent storage (survives Railway restarts) ──
DATA_FILE = '/tmp/user_data.json'

def load_user_data():
    global user_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                user_data = json.load(f)
            logger.info(f"Loaded {len(user_data)} sessions from disk")
    except Exception as e:
        logger.warning(f"load_user_data error: {e}")
        user_data = {}

def save_user_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(user_data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"save_user_data error: {e}")

load_user_data()

def build_ods_num(d):
    import datetime as _dt
    yr = _dt.datetime.now().strftime('%y')
    num = str(d.get('project_num') or '000').zfill(3)
    addr = (d.get('addr') or '')
    addr_lines = [l.strip() for l in addr.split('\n') if l.strip()]
    city_line = addr_lines[1] if len(addr_lines) >= 2 else (addr_lines[0] if addr_lines else '')
    A = city_line[0].upper() if city_line else 'X'
    name = (d.get('name') or '')
    B = name[0].upper() if name else 'X'
    service = (d.get('service') or '')
    C = service[0].upper() if service else 'X'
    return f"ODS{yr}-{num}-{A}{B}{C}"

def build_short_title(d):
    service = (d.get('service') or '').strip().lower()
    if 'avis' in service:
        return 'Avis-expert'
    if 'inspection des fond' in service:
        return 'Fondations'
    if 'inspection' in service:
        return 'Inspection'
    if 'enl' in service or 'mur porteur' in service:
        return 'Mur-porteur'
    if 'fissure' in service or 'valuation' in service:
        return 'Fissures'
    if 'soutenement' in service or 'sout' in service:
        return 'Soutenement'
    if 'sous-sol' in service or 'sous sol' in service:
        return 'Sous-sol'
    if 'conception' in service:
        return 'Conception'
    if 'amenagement' in service or 'ménagement' in service:
        return 'Reamenagement'
    if 'analyse' in service:
        return 'Analyse-struct'
    words = (d.get('service') or '').split()
    return '-'.join(words[:2]) if words else 'Mandat'


MISSING_QUESTIONS = {
    'name':  '✏️ Nom du client?',
    'phone': '📞 Numéro de téléphone?',
    'email': '📧 Adresse courriel?',
    'addr':  '📍 Adresse complète du projet?\n(ex: 247 Rue Beaumont\nGranby QC J2G 8S4\nCanada)',
    'project_num': '🔢 Numéro du projet? (ex: 062)',
    'delai': '⏱️ Délai estimé (jours ouvrables)? (ex: 8)',
}

def get_missing_fields(d):
    missing = []
    # project_num first
    if not d.get('project_num'):
        missing.append('project_num')
    for key in ['name', 'phone', 'email']:
        val = (d.get(key) or '').strip()
        if not val or val in ('-', 'None'):
            missing.append(key)
    return missing

def show_format_buttons(chat_id, d):
    try:
        price = d.get('price', 0)
        ods = build_ods_num(d) + '-' + build_short_title(d)
        d['odsNum'] = ods
        save_user_data()
    except Exception as e:
        logger.error('show_format_buttons init error: ' + str(e))
        price = d.get('price', 0)
        ods = d.get('odsNum', 'ODS')
    lines = [
        "✅ *Prêt à générer*",
        "",
        "👤 " + (d.get('name') or '—'),
        "📍 " + (d.get('addr') or '—'),
        "📞 " + (d.get('phone') or '—'),
        "📧 " + (d.get('email') or '—'),
        "🏠 " + (d.get('property_type') or '—'),
        "⏱️ " + (d.get('delai') or '—'),
        "",
        "🔧 " + (d.get('service') or '—'),
        "💰 $" + "{:,}".format(price) + " CAD",
        "📄 " + ods,
        "",
        "Format?",
    ]
    msg = "\n".join(lines)
    kb = [
        [{'text': '📊 Excel', 'callback_data': 'xl'}, {'text': '📄 PDF', 'callback_data': 'pdf'}],
        [{'text': '✏️ Changer prix', 'callback_data': 'price'}],
        [{'text': '🔄 Nouveau client', 'callback_data': 'nouveau'}],
    ]
    tg(chat_id, msg, kb)

    # Send ready-to-copy email text
    try:
        client_email = d.get('email') or 'Non indiqué'
        client_name = d.get('name') or ''
        ods_num = d.get('odsNum') or ''
        service = d.get('service') or ''
        addr = (d.get('addr') or '').replace('\n', ', ')
        # 3 separate messages for easy copy/paste
        tg(chat_id, "📧 *À:*\n" + client_email)
        tg(chat_id, "📋 *Objet:*\n" + ods_num + " – Offre de service – " + client_name)
        # Get last name for formal greeting
        name_parts = client_name.strip().split()
        last_name = name_parts[-1] if name_parts else client_name
        body_msg = (
            "Bonjour M./Mme " + last_name + ",\n\n"
            "Veuillez trouver ci-joint notre offre de service " + ods_num
            + " concernant " + service.lower()
            + " pour le projet situé au " + addr + ".\n\n"
            "N'hésitez pas à nous contacter pour toute question.\n\n"
            "Cordialement,"
        )
        tg(chat_id, "✉️ *Corps du message:*\n\n" + body_msg)
    except Exception as e:
        logger.error('email draft error: ' + str(e))


def ask_desc_options(chat_id, uid):
    uid = str(uid)
    d = user_data.get(uid, {})
    try:
        tg(chat_id, "✍️ Génération des descriptions techniques...")
        service = d.get('service', '')
        raw_desc = d.get('desc', '')
        property_type = d.get('property_type', '')
        addr = d.get('addr', '')
        # If service_lines already extracted, use them as option 1
        existing_lines = d.get('service_lines', [])
        existing_desc = d.get('desc', '')

        prompt = (
            "You are a structural engineering expert at Métra Structure Inc. "
            "Generate exactly 3 different professional mandate descriptions IN FRENCH (2-3 sentences each, technical). "
            "Service: " + service + ". Property: " + property_type + ". "
            "Address: " + addr + ". Context: " + raw_desc + ". "
            "Make each option distinct in approach and detail level. "
            "Return ONLY JSON array: [\"desc1\", \"desc2\", \"desc3\"]"
        )
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        result = "".join(b.text for b in response.content if hasattr(b, "text"))
        result = result.replace("```json", "").replace("```", "").strip()
        options = json.loads(result)
        d["desc_options"] = options
        user_data[uid] = d
        save_user_data()
        # Show full descriptions then buttons
        msg_lines = ["📋 *Choisissez la description technique:*\n"]
        for i, opt in enumerate(options):
            msg_lines.append(f"*{i+1}.* {opt}\n")
        msg_lines.append("_Appuyez sur le bouton correspondant:_")
        tg(chat_id, "\n".join(msg_lines))
        kb = []
        for i in range(len(options)):
            kb.append([{"text": f"✅ Option {i+1}", "callback_data": "desc_" + str(i)}])
        kb.append([{"text": "✏️ Écrire ma propre description", "callback_data": "desc_custom"}])
        tg(chat_id, "👇 Votre choix:", kb)
    except Exception as e:
        import traceback
        logger.error("ask_desc_options error: " + str(e) + "\n" + traceback.format_exc())
        tg(chat_id, "❌ Erreur description: " + str(e))
        # Don't skip — ask user to write manually
        d["waiting_field"] = "desc"
        d["desc_confirmed"] = False
        user_data[uid] = d
        save_user_data()
        tg(chat_id, "✏️ Écrivez la description du mandat manuellement:")

def ask_next_missing(chat_id, uid):
    d = user_data.get(uid, {})
    missing = get_missing_fields(d)
    if missing:
        field = missing[0]
        d['waiting_field'] = field
        user_data[uid] = d
        save_user_data()
        tg(chat_id, MISSING_QUESTIONS[field] + "\n\n_(Tapez /nouveau pour recommencer)_")
    elif not d.get('addr_confirmed'):
        addr = (d.get('addr') or '').strip()
        if not addr or addr in ('—', 'Non indiqué', 'None'):
            # Completely missing — ask
            d['waiting_field'] = 'addr'
            user_data[uid] = d
            save_user_data()
            tg(chat_id, "📍 Adresse complète du projet?\n(ex: 247 Rue Beaumont\nGranby QC H1A 1A1\nCanada)")
        else:
            # Complete — show confirm buttons (no waiting_field set, buttons handle it)
            addr_display = addr.replace('\n', ', ')
            d['waiting_field'] = None
            user_data[uid] = d
            save_user_data()
            kb = [
                [{'text': '✅ Confirmer', 'callback_data': 'addr_ok'},
                 {'text': '✏️ Modifier', 'callback_data': 'addr_edit'}]
            ]
            tg(chat_id, "📍 Adresse détectée :\n" + addr_display + "\n\nCorrect?", kb)
    elif not d.get('desc_confirmed'):
        executor.submit(ask_desc_options, chat_id, uid)
    elif not d.get('project_num'):
        d['waiting_field'] = 'project_num'
        user_data[uid] = d
        save_user_data()
        tg(chat_id, "🔢 Numéro du projet? (ex: 062)\n\n_(Tapez /nouveau pour recommencer)_")
    elif not d.get('delai'):
        d['waiting_field'] = 'delai'
        user_data[uid] = d
        save_user_data()
        tg(chat_id, MISSING_QUESTIONS['delai'])
    else:
        show_format_buttons(chat_id, d)


def tg(chat_id, text, keyboard=None):
    payload = {'chat_id': chat_id, 'text': text}
    if keyboard:
        payload['reply_markup'] = {'inline_keyboard': keyboard}
    try:
        r2 = req.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json=payload, timeout=15)
        logger.info(f"tg sent: {r2.status_code} to {chat_id}")
        if r2.status_code != 200:
            logger.error(f"tg response: {r2.text[:200]}")
    except Exception as e:
        logger.error(f"tg error: {e}")

def tg_doc(chat_id, buf, filename, caption):
    try:
        buf.seek(0)
        file_bytes = buf.read()
        logger.info(f"tg_doc: sending {filename}, size={len(file_bytes)} bytes to {chat_id}")
        resp = req.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendDocument',
            data={'chat_id': chat_id, 'caption': caption},
            files={'document': (filename, file_bytes)},
            timeout=60)
        logger.info(f"tg_doc response: {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        import traceback
        logger.error(f"tg_doc error: {e}")
        logger.error(traceback.format_exc())
        tg(chat_id, f"❌ Erreur envoi fichier: {str(e)}")

def draw_header_footer(canvas, doc):
    canvas.saveState()
    canvas.drawImage(LOGOS['metra'], 1.8*cm, H-3.0*cm, width=2.8*cm, height=1.8*cm, preserveAspectRatio=True, mask='auto')
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawCentredString(W/2, H-1.7*cm, 'Ingénierie des structures / Structural Engineering')
    canvas.setFont('Helvetica', 9)
    canvas.drawCentredString(W/2, H-2.2*cm, '1610-1280 Rue Saint-Jacques')
    canvas.drawCentredString(W/2, H-2.7*cm, 'Montréal – Québec- Canada  H3C 0G1')
    canvas.setFillColor(colors.HexColor('#1155CC'))
    canvas.drawCentredString(W/2, H-3.2*cm, 'info@metrastructure.ca | (438) 867-4131')
    canvas.setFillColor(BLACK)
    canvas.setLineWidth(1)
    canvas.line(1.8*cm, H-3.6*cm, W-1.8*cm, H-3.6*cm)
    canvas.setLineWidth(0.5)
    canvas.line(1.8*cm, 2.0*cm, W-1.8*cm, 2.0*cm)
    canvas.drawImage(LOGOS['ing'],  2*cm,  0.3*cm, width=2*cm,  height=1.4*cm, preserveAspectRatio=True, mask='auto')
    canvas.drawImage(LOGOS['peo'],  8*cm,  0.3*cm, width=3*cm,  height=1.4*cm, preserveAspectRatio=True, mask='auto')
    canvas.drawImage(LOGOS['rgcq'],15*cm,  0.3*cm, width=2*cm,  height=1.4*cm, preserveAspectRatio=True, mask='auto')
    canvas.setFont('Helvetica', 8)
    canvas.drawRightString(W-1.8*cm, 0.6*cm, f'{doc.page} | Page')
    canvas.restoreState()

def _build_service_desc(data):
    """Max 4 short bullet lines for PDF table cell."""
    # Priority: service_lines from extraction
    raw = data.get('service_lines') or []
    if not raw:
        import re as _re
        desc = data.get('desc') or data.get('service') or ''
        raw = [p.strip() for p in _re.split(r'[;.\n]', desc) if p.strip()]
    result = []
    for line in raw[:4]:
        result.append('• ' + line.rstrip(';. ') + ';')
    return '<br/>'.join(result) if result else data.get('service', '')

def generate_pdf(data):
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=letter,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=4.0*cm, bottomMargin=2.4*cm)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
    doc.addPageTemplates([PageTemplate(id='all', frames=frame, onPage=draw_header_footer)])

    def s(name, font='Helvetica', size=10, leading=13, align=TA_LEFT, sb=0, sa=0):
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
                              textColor=BLACK, alignment=align, spaceBefore=sb, spaceAfter=sa)

    sn=s('n'); sb_=s('b',font='Helvetica-Bold'); sh=s('h',font='Helvetica-Bold',sb=6,sa=2)
    sr=s('r',align=TA_RIGHT); sj=s('j',leading=13,sb=3,sa=3)
    sc=s('cadre',font='Helvetica-Bold',size=10,leading=14,sb=6,sa=4,align=TA_CENTER)
    shb=s('hb',font='Helvetica-Bold',align=TA_CENTER); shn=s('hn',align=TA_CENTER); str_=s('tr',align=TA_RIGHT)

    price = float(data.get('price', 3200))
    pf = f'$ {price:,.2f}'
    story = []

    story.append(Paragraph(f'Date :  {data.get("date", datetime.now().strftime("%Y-%m-%d"))}', sr))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'M./Mme {data.get("name") or "—"}', sn))
    addr_single = ', '.join(l.strip() for l in (str(data.get('addr') or '')).split('\n') if l.strip())
    story.append(Paragraph('Adresse : ' + (addr_single or '—'), sn))
    story.append(Paragraph(f'Cell.: {data["phone"]}', sn))
    story.append(Paragraph(f'Courriel : {data["email"]}', sn))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f'<b>{data["odsNum"]}</b>', sn))
    story.append(Paragraph('CADRE CONTRACTUEL – PROPOSITION DE SERVICES | MÉTRA STRUCTURE INC.', sc))
    story.append(Paragraph(
        "L'équipe de Métra Structure Inc. vous remercie pour votre confiance à l'égard de notre proposition de services. "
        "Nous vous informons que la présente offre, ainsi que les conditions qui l'accompagnent, forment un accord unique et indissociable. "
        "Toute acceptation de cette offre vaut acceptation complète et sans réserve de l'ensemble des modalités qui y sont énoncées. "
        "Aux fins des présentes, le terme « Client » réfère à la personne, physique ou morale, qui confie le mandat et qui demeure responsable du paiement des honoraires afférents.", sj))

    for heading, text in [
        ("1. Description des services","Métra Structure Inc. offre ses services d'ingénierie-conseil conformément aux cadres légaux, aux normes en vigueur et aux règles professionnelles applicables, notamment celles de l'Ordre des ingénieurs du Québec (OIQ) et de Professional Engineers Ontario (PEO), pour le périmètre défini au mandat. Les services sont fournis selon une obligation de moyens et non de résultat. La responsabilité de Métra Structure Inc. ne pourra excéder, sous réserve des dispositions légales applicables, le montant des honoraires payés pour le présent mandat."),
        ("2. Versement initial","À défaut d'une entente écrite contraire, un acompte représentant 25 % du montant total de l'offre de services est requis au moment de la signature."),
        ("3. Honoraires et modalités de paiement","Les honoraires et frais remboursables sont facturés selon la progression des travaux et sont exigibles dès réception de la facture. Tout montant non réglé dans un délai de trente (30) jours sera assujetti à des intérêts de 1,5 % par mois (19,56 % par année). En cas de non-paiement, Métra Structure Inc. pourra suspendre la prestation des services. Les taxes applicables s'ajoutent aux honoraires."),
        ("4. Gestion des retards et arrêt du projet","En cas de suspension ou d'annulation du projet, le client est responsable du paiement des coûts engagés et des prestations réalisées jusqu'à la date de notification écrite."),
        ("5. Cadre contractuel","Ce document tient lieu d'entente complète entre les parties. Aucun changement ne sera valide à moins d'être formulé par écrit."),
    ]:
        story.append(Paragraph(f'<b>{heading}</b>', sh))
        story.append(Paragraph(text, sj))

    story.append(PageBreak())
    story.append(Paragraph('<b>6. Présence sur site et logistique</b>', sh))
    story.append(Paragraph("Toute requête de déplacement doit être transmise au moins 48 heures avant la date prévue.", sj))
    story.append(Spacer(1, 4))
    story.append(Paragraph('<b>TAUX HORAIRES</b>', sb_))
    story.append(Spacer(1, 3))
    rt = Table([[Paragraph(r, str_), Paragraph(v, sn)] for r,v in [
        ('Ingénieur senior :','130 $ /h'),('Ingénieur intermédiaire :','110 $ /h'),
        ('Ingénieur junior :','105 $ /h'),('Technicien :','100 $ /h'),('Dessinateur :','85 $ /h'),
    ]], colWidths=[9*cm, 3*cm])
    rt.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
    story.append(rt)
    story.append(Spacer(1, 6))
    story.append(Paragraph('<b>HONORAIRES – FORFAIT DU PROJET</b>', sb_))
    story.append(Spacer(1, 5))
    hon_data = [
        [Paragraph('<b>Description des services</b>',shb),Paragraph('<b>Unité</b>',shb),Paragraph('<b>Quantité</b>',shb),Paragraph('<b>Coût unitaire</b>',shb),Paragraph('<b>Coût total</b>',shb)],
        [Paragraph(_build_service_desc(data),s('sd',leading=14)),Paragraph('Forfait',shn),Paragraph('1',shn),Paragraph(pf,shn),Paragraph(pf,shn)],
        ['','','',Paragraph('Total des honoraires du projet',str_),Paragraph(f'<b>{pf}</b>',shb)],
    ]
    ht = Table(hon_data, colWidths=[8.5*cm,1.8*cm,1.8*cm,3.8*cm,2.6*cm])
    ht.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5,BLACK),('INNERGRID',(0,0),(-1,-1),0.5,BLACK),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('SPAN',(0,2),(2,2)),
    ]))
    story.append(ht)
    story.append(Spacer(1, 8))
    story.append(Paragraph('<b>AUTRES FRAIS (SI APPLICABLE)</b>', sb_))
    story.append(Spacer(1, 5))
    story.append(Paragraph('Le délai de livraison estimé est de ' + (data.get('delai') or '10') + ' jours ouvrables suivant la visite finale sur site.', sn))
    story.append(Spacer(1, 6))
    story.append(Paragraph('<b>Cette offre est basée sur les hypothèses suivantes :</b>', sb_))
    for h in [
        "1- Plans architecturaux fournis avant le début du mandat (si disponible);",
        "2- Accès aux éléments structuraux accessibles (colonnes, poutres, murs porteurs, fondations);",
        "3- Vérification et approbation par l'architecte non incluses dans la présente offre.",
    ]:
        story.append(Paragraph(h, sn))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Cette offre est valable 30 jours. Pour l'accepter, veuillez compléter les sections suivantes.", sn))
    story.append(Spacer(1, 16))
    sig = Table([
        [Paragraph('<b>Arash Rohani</b> , ing., P.Eng.',sn),Paragraph('<b>Nom du client:</b>',sn)],
        [Paragraph('Président-Ingénieur en structure',sn),''],
        [Paragraph('Métra Structure Inc.',sn),Paragraph('<b>Date:</b>',sn)],
    ], colWidths=[9*cm,8.5*cm])
    sig.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.append(sig)
    doc.build(story)
    buf.seek(0)
    return buf

def generate_excel(data):
    template = os.path.join(BASE, 'template.xlsx')
    out_path = f"/tmp/{data['odsNum']}.xlsx"
    shutil.copy(template, out_path)
    wb = openpyxl.load_workbook(out_path)
    ws = wb['ODS']
    ws['B7'] = f"M./Mme {data.get('name') or '—'}"
    ws['B8'] = (data.get('addr') or '').replace('\n', ', ')
    ws['B9'] = f"Cell.: {data['phone']}"
    ws['B10'] = f"Courriel : {data['email']}"
    ws['B12'] = f"{data.get('odsNum','ODS')}-{(data.get('name') or 'client').replace(' ','-')}"
    ws['B47'] = data.get('desc', data.get('service',''))
    ws['C47'] = 'Forfait'
    ws['D47'] = 1
    ws['E47'] = float(data['price'])
    ws['F47'] = '=E47*D47'
    ws['F48'] = '=SUM(F47:F47)'
    wb.save(out_path)
    with open(out_path, 'rb') as f:
        buf = io.BytesIO(f.read())
    os.remove(out_path)
    buf.seek(0)
    return buf

def do_extract(chat_id, uid, file_id):
    uid = str(uid)  # ensure string key
    try:
        r = req.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}', timeout=10)
        fpath = r.json()['result']['file_path']
        img_r = req.get(f'https://api.telegram.org/file/bot{BOT_TOKEN}/{fpath}', timeout=15)
        img_b64 = base64.b64encode(img_r.content).decode()

        prompt = """Extract client info from this document. Return ONLY JSON:
{"client_name":"","phone":"","email":"","address":"","soumission_ref":"","project_description":"","property_type":"","suggested_service":"","suggested_price":0}
suggested_service from: "Analyse structurale générale","Inspection et rapport structural","Avis d'expert — stabilisation et renforcement","Enlèvement de mur porteur","Inspection des fondations","Évaluation des fissures et désordres structuraux","Mur de soutènement","Conception structurale complète","Analyse structurale — sous-sol et ajout au-dessus du garage","Réaménagement intérieur avec modification structurale"
suggested_price: CAD integer. ONLY JSON."""

        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1200,
            temperature=0,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":img_b64}},
                {"type":"text","text":prompt}
            ]}]
        )
        text = ''.join(b.text for b in response.content if hasattr(b,'text'))
        info = json.loads(text.replace('```json','').replace('```','').strip())

        yr = datetime.now().strftime('%y')
        ods_num = f"ODS{yr}-{random.randint(100,999)}"
        price = info.get('suggested_price') or PRICES.get(info.get('suggested_service',''), 3200)

        user_data[uid] = {
            'name': info.get('client_name',''),
            'phone': info.get('phone',''),
            'email': info.get('email',''),
            'addr': info.get('address',''),
            'desc': info.get('project_description',''),
            'service': info.get('suggested_service',''),
            'price': price,
            'odsNum': ods_num,
            'date': datetime.now().strftime('%Y-%m-%d'),
        }
        save_user_data()
        ask_next_missing(chat_id, uid)
    except Exception as e:
        import traceback
        logger.error(f"Extract error: {e}")
        logger.error(traceback.format_exc())
        tg(chat_id, f"❌ Erreur: {str(e)}")

def do_extract_text(chat_id, uid, client_text):
    uid = str(uid)
    try:
        PROMPT = (
            "Extract client info from this email/text. Return ONLY JSON with these keys: "
            "client_name, phone, email, address, soumission_ref, project_description, property_type, suggested_service, suggested_price. "
            "For address: extract ALL components (street, city, province, postal code, country). ""Format: \"123 Rue Exemple\\nMontréal QC H1A 1A1\\nCanada\". ""If postal code missing, infer from city. If province missing, infer from city name. Always end with Canada. "
            "suggested_service must be one of: Analyse structurale generale, Inspection et rapport structural, "
            "Avis d expert stabilisation et renforcement, Enlevement de mur porteur, Inspection des fondations, "
            "Evaluation des fissures et desordres structuraux, Mur de soutenement, Conception structurale complete, "
            "Analyse structurale sous-sol et ajout au-dessus du garage, Reamenagement interieur avec modification structurale. "
            "suggested_price: integer CAD. ONLY JSON, no markdown.\n\nText:\n"
        ) + client_text

        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=800,
            messages=[{"role": "user", "content": PROMPT}]
        )
        result = ''.join(b.text for b in response.content if hasattr(b, 'text'))
        result = result.replace('```json', '').replace('```', '').strip()
        info = json.loads(result)

        yr = datetime.now().strftime('%y')
        ods_num = "ODS" + yr + "-" + str(random.randint(100, 999))
        price = info.get('suggested_price') or PRICES.get(info.get('suggested_service', ''), 3200)

        user_data[uid] = {
            'name': info.get('client_name', ''),
            'phone': info.get('phone', ''),
            'email': info.get('email', ''),
            'addr': info.get('address', ''),
            'desc': info.get('project_description', ''),
            'service': info.get('suggested_service', ''),
            'price': price,
            'odsNum': ods_num,
            'date': datetime.now().strftime('%Y-%m-%d'),
        }
        save_user_data()

        def s(v): return str(v) if v else '—'
        name = s(info.get('client_name'))
        addr = s(info.get('address'))
        phone = s(info.get('phone'))
        email = s(info.get('email'))
        ptype = s(info.get('property_type'))
        service = s(info.get('suggested_service'))
        msg_out = (
            "✅ *Informations extraites*\n\n"
            "👤 " + name + "\n"
            "📍 " + addr + "\n"
            "📞 " + phone + "\n"
            "📧 " + email + "\n"
            "🏠 " + ptype + "\n\n"
            "🔧 " + service + "\n"
            "💰 $" + "{:,}".format(price) + " CAD\n"
            "📄 " + ods_num + "\n\nFormat?"
        )
        kb = [
            [{'text': '📊 Excel', 'callback_data': 'xl'}, {'text': '📄 PDF', 'callback_data': 'pdf'}],
            [{'text': '✏️ Changer prix', 'callback_data': 'price'}]
        ]
        tg(chat_id, msg_out, kb)
    except Exception as e:
        import traceback
        logger.error("do_extract_text error: " + str(e))
        logger.error(traceback.format_exc())
        tg(chat_id, "❌ Erreur extraction: " + str(e))

def do_excel(chat_id, uid):
    uid = str(uid)
    d = user_data.get(uid)
    logger.info(f"do_excel called: uid={uid}, data={d is not None}")
    if not d:
        tg(chat_id, "❌ Session expirée. Envoyez une nouvelle photo.")
        return
    try:
        logger.info(f"Generating Excel for {d.get('name','?')}")
        tg(chat_id, "⏳ Génération Excel...")
        buf = generate_excel(d)
        fname = "{}_{}. xlsx".format(d.get('odsNum','ODS'), (d.get('name') or 'client').replace(' ','-')).replace(' ','')
        logger.info(f"Excel generated, sending {fname}")
        tg_doc(chat_id, buf, fname, f"✅ Excel — ${d['price']:,} CAD")
    except Exception as e:
        import traceback
        logger.error(f"do_excel error: {e}")
        logger.error(traceback.format_exc())
        tg(chat_id, f"❌ Erreur Excel: {str(e)}")

def do_pdf(chat_id, uid):
    uid = str(uid)
    d = user_data.get(uid)
    logger.info(f"do_pdf called: uid={uid}, data={d is not None}")
    if not d:
        tg(chat_id, "❌ Session expirée. Envoyez une nouvelle photo.")
        return
    try:
        # Send email draft FIRST so user can copy before switching to Outlook
        try:
            client_email = d.get('email') or 'Non indiqué'
            client_name = d.get('name') or ''
            ods_num = d.get('odsNum') or ''
            service = d.get('service') or ''
            addr = (d.get('addr') or '').replace('\n', ', ')
            name_parts = client_name.strip().split()
            first_name = name_parts[0] if name_parts else ''
            last_name = name_parts[-1] if len(name_parts) > 1 else client_name
            female_names = ('marie','sophie','julie','jessica','isabelle','nathalie','caroline',
                            'maude','cindy','josiane','véronique','stephanie','catherine','sarah',
                            'laura','emma','alice','claire','anne','christine','michèle','lucie',
                            'audrey','camille','chantal','diane','france','ginette','helene','lea',
                            'manon','nicole','patricia','rachel','sylvie','valerie','yasmine')
            female_endings = ('a','ie','ine','elle','ette','anne','ène')
            fn_lower = first_name.lower().rstrip('.')
            is_female = fn_lower in female_names or any(fn_lower.endswith(e) for e in female_endings)
            title = "Mme" if is_female else "M."
            tg(chat_id, "📋 *Copiez avant d'ouvrir Outlook:*")
            tg(chat_id, client_email)
            tg(chat_id, ods_num + " – Offre de service – " + client_name)
            body_msg = (
                "Bonjour " + title + " " + last_name + ",\n\n"
                "Veuillez trouver ci-joint notre offre de service " + ods_num
                + " concernant " + service.lower()
                + " pour le projet situé au " + addr + ".\n\n"
                "N'hésitez pas à nous contacter pour toute question.\n\n"
                "Cordialement,"
            )
            tg(chat_id, body_msg)
            tg(chat_id, "👆 Copiez le texte ci-dessus, puis ouvrez le PDF ↓")
        except Exception as e:
            logger.error('email draft in do_pdf error: ' + str(e))

        logger.info(f"Generating PDF for {d.get('name','?')}")
        tg(chat_id, "⏳ Génération PDF...")
        buf = generate_pdf(d)
        fname = "{}_{}.pdf".format(d.get('odsNum','ODS'), (d.get('name') or 'client').replace(' ','-'))
        logger.info(f"PDF generated, sending {fname}")
        tg_doc(chat_id, buf, fname, f"✅ PDF — ${d['price']:,} CAD")
    except Exception as e:
        import traceback
        logger.error(f"do_pdf error: {e}")
        logger.error(traceback.format_exc())
        tg(chat_id, f"❌ Erreur PDF: {str(e)}")

@app.route('/')
def index():
    with open(os.path.join(BASE, 'index.html'), 'r', encoding='utf-8') as f:
        return Response(f.read(), mimetype='text/html')

@app.route('/api/extract', methods=['POST'])
def api_extract():
    data = request.json
    prompt = """Extract client info. Return ONLY JSON: {"client_name":"","phone":"","email":"","address":"","soumission_ref":"","project_description":"","property_type":"","suggested_service":"","suggested_price":0}"""
    response = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=800,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":data.get('mime','image/jpeg'),"data":data.get('image')}},
            {"type":"text","text":prompt}
        ]}]
    )
    text = ''.join(b.text for b in response.content if hasattr(b,'text'))
    return jsonify(json.loads(text.replace('```json','').replace('```','').strip()))

@app.route('/api/generate-pdf', methods=['POST'])
def api_pdf():
    data = request.json
    buf = generate_pdf(data)
    filename = f"{data.get('odsNum','ODS')}_{data.get('name','client').replace(' ','-')}.pdf"
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)

def handle_update(data):
    """Process Telegram update in background thread — webhook returns immediately"""
    try:
        msg = data.get('message', {})
        cb = data.get('callback_query', {})

        if cb:
            uid = str(cb['from']['id'])
            chat_id = cb['message']['chat']['id']
            cdata = cb.get('data', '')
            # Answer callback immediately to remove loading spinner
            try:
                req.post(f'https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery',
                         json={'callback_query_id': cb['id']}, timeout=3)
            except:
                pass
            logger.info(f"CB: {cdata} uid={uid} has_data={uid in user_data} keys={list(user_data.keys())}")
            if cdata in ('xl', 'pdf'):
                if uid not in user_data:
                    tg(chat_id, "❌ Session expirée. Envoyez une nouvelle photo.")
                elif cdata == 'xl':
                    do_excel(chat_id, uid)
                else:
                    do_pdf(chat_id, uid)
            elif cdata == 'addr_ok':
                d = user_data.get(uid, {})
                d['addr_confirmed'] = True
                d['waiting_field'] = None
                user_data[uid] = d
                save_user_data()
                ask_next_missing(chat_id, uid)
            elif cdata == 'addr_edit':
                d = user_data.get(uid, {})
                d['addr_confirmed'] = False
                d['waiting_field'] = 'addr'
                user_data[uid] = d
                save_user_data()
                tg(chat_id, "📍 Entrez l'adresse complète:\n(ex: 247 Rue Beaumont\nGranby QC J2G 8S4\nCanada)")
            elif cdata.startswith('desc_'):
                d = user_data.get(uid, {})
                if cdata == 'desc_custom':
                    d['waiting_field'] = 'desc'
                    d['desc_confirmed'] = False
                    user_data[uid] = d
                    save_user_data()
                    tg(chat_id, "✏️ Écrivez votre description technique:")
                else:
                    idx = int(cdata.split('_')[1])
                    options = d.get('desc_options', [])
                    if idx < len(options):
                        d['desc'] = options[idx]
                        d['desc_confirmed'] = True
                        d['waiting_field'] = None
                        user_data[uid] = d
                        save_user_data()
                        tg(chat_id, "✅ Description sélectionnée.")
                        ask_next_missing(chat_id, uid)
            elif cdata == 'nouveau':
                user_data.pop(uid, None)
                save_user_data()
                tg(chat_id, "👋 *Nouveau client*\n\n📸 Envoyez une photo ou collez le texte du client.")
            elif cdata == 'price':
                d = user_data.get(uid, {})
                d['waiting_price'] = True
                d['waiting_field'] = None
                user_data[uid] = d
                tg(chat_id, "💰 Entrez le nouveau prix (ex: 3500):")

        elif msg:
            uid = str(msg['from']['id'])
            chat_id = msg['chat']['id']
            if msg.get('text'):
                text = msg['text']
                if text in ('/start', '/nouveau'):
                    user_data.pop(uid, None)
                    save_user_data()
                    tg(chat_id, "👋 *Métra Structure — Nouveau client*\n\n📸 Envoyez une photo ou collez le texte du client.")
                    return
                d = user_data.get(uid, {})
                if d.get('waiting_price'):
                    try:
                        price = int(text.strip().replace('$','').replace(',','').replace(' ',''))
                        d['price'] = price
                        d['waiting_price'] = False
                        d['waiting_field'] = None
                        user_data[uid] = d
                        save_user_data()
                        show_format_buttons(chat_id, d)
                    except:
                        tg(chat_id, "❌ Nombre invalide (ex: 3500)")
                elif d.get('waiting_field'):
                    field = d['waiting_field']
                    if False:
                        pass
                    else:
                        d[field] = text.strip()
                        d['waiting_field'] = None
                        if field == 'addr':
                            d['addr_confirmed'] = True
                        if field == 'desc':
                            d['desc_confirmed'] = True
                        user_data[uid] = d
                        save_user_data()
                        ask_next_missing(chat_id, uid)
                else:
                    if len(text) > 50:
                        tg(chat_id, "🔍 Extraction en cours...")
                        executor.submit(do_extract_text, chat_id, uid, text)
                    else:
                        tg(chat_id, "📸 Envoyez une photo ou collez le texte du client.")
            elif msg.get('photo'):
                # Guard against double processing
                d = user_data.get(uid, {})
                if d.get('extracting'):
                    return
                d['extracting'] = True
                user_data[uid] = d
                save_user_data()
                file_id = msg['photo'][-1]['file_id']
                tg(chat_id, "🔍 Extraction en cours...")
                executor.submit(do_extract, chat_id, uid, file_id)
    except Exception as e:
        import traceback
        logger.error(f"handle_update error: {e}\n{traceback.format_exc()}")

@app.route('/webhook/telegram', methods=['POST'])
def webhook():
    data = request.get_json(force=True, silent=True)
    if data:
        executor.submit(handle_update, data)
    return 'ok', 200

@app.route('/setup')
def setup():
    """Register Telegram webhook — call once after deploy"""
    railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if not railway_url:
        railway_url = 'web-production-e1b99.up.railway.app'
    webhook_url = f"https://{railway_url}/webhook/telegram"
    r = req.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook',
        json={"url": webhook_url, "allowed_updates": ["message","callback_query"]},
        timeout=15
    )
    info = req.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo', timeout=10)
    return jsonify({"set": r.json(), "info": info.json()})

@app.route('/status')
def status():
    return jsonify({"users": len(user_data), "keys": list(user_data.keys())})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
