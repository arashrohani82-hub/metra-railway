import os, json, io, shutil, base64, logging, threading
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
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

# ── PDF Generator ────────────────────────────────────────────────────
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

    story.append(Paragraph(f'Date :  {data["date"]}', sr))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'M./Mme {data["name"]}', sn))
    story.append(Paragraph(f'Adresse: :{data["addr"]}', sn))
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
    story.append(Paragraph("Toute requête impliquant une visite ou un déplacement sur le chantier doit être transmise au moins quarante-huit (48) heures avant la date prévue.", sj))
    story.append(Spacer(1, 6))
    story.append(Paragraph('<b>TAUX HORAIRES</b>', sb_))
    story.append(Spacer(1, 3))
    rt = Table([[Paragraph(r, str_), Paragraph(v, sn)] for r,v in [
        ('Ingénieur senior :','130 $ /h'),('Ingénieur intermédiaire :','110 $ /h'),
        ('Ingénieur junior :','105 $ /h'),('Technicien :','100 $ /h'),('Dessinateur :','85 $ /h'),
    ]], colWidths=[9*cm, 3*cm])
    rt.setStyle(TableStyle([('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2)]))
    story.append(rt)
    story.append(Spacer(1, 10))
    story.append(Paragraph('<b>HONORAIRES – FORFAIT DU PROJET</b>', sb_))
    story.append(Spacer(1, 5))
    hon_data = [
        [Paragraph('<b>Description des services</b>',shb),Paragraph('<b>Unité</b>',shb),Paragraph('<b>Quantité</b>',shb),Paragraph('<b>Coût unitaire</b>',shb),Paragraph('<b>Coût total</b>',shb)],
        [Paragraph(data.get('desc', data.get('service','')),s('sd',leading=13)),Paragraph('Forfait',shn),Paragraph('1',shn),Paragraph(pf,shn),Paragraph(pf,shn)],
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
    story.append(Paragraph('Le délai de livraison estimé est de 10 jours ouvrables suivant la visite finale sur site.', sn))
    story.append(Spacer(1, 6))
    story.append(Paragraph('<b>Cette offre est basée sur les hypothèses suivantes :</b>', sb_))
    for h in [
        "1-Les plans architecturaux et structuraux seront fournis avant le début du mandat(si disponible )",
        "2-Accès à l'ensemble des éléments structuraux accessibles, incluant notamment les colonnes, les poutres, les murs porteurs, les murs de contreventement ainsi que les fondations, lorsque applicable",
        "3-La vérification, la coordination et l'approbation par l'architecte ou le technologue ne sont pas incluses dans la présente offre de service.",
    ]:
        story.append(Paragraph(h, sn))
    story.append(Spacer(1, 8))
    story.append(Paragraph("La présente offre est valable pour une durée de trente (30) jours. Afin de l'accepter, veuillez compléter les sections suivantes.", sn))
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
    output = f"/tmp/{data['odsNum']}.xlsx"
    shutil.copy(template, output)
    wb = openpyxl.load_workbook(output)
    ws = wb['ODS']
    ws['B7'] = f"M./Mme {data['name']}"
    ws['B8'] = f"Adresse: :{data['addr']}"
    ws['B9'] = f"Cell.: {data['phone']}"
    ws['B10'] = f"Courriel : {data['email']}"
    ws['B12'] = f"{data['odsNum']}-{data['name'].replace(' ','-')}"
    ws['B47'] = data.get('desc', data.get('service',''))
    ws['C47'] = 'Forfait'
    ws['D47'] = 1
    ws['E47'] = float(data['price'])
    ws['F47'] = '=E47*D47'
    ws['F48'] = '=SUM(F47:F47)'
    wb.save(output)
    return output

def extract_info(img_b64, mime='image/jpeg'):
    prompt = """This is a client document (SoumissionRenovation.ca screenshot, email, or form).
Extract all client and project information. Return ONLY a valid JSON object:
{"client_name":"","phone":"","email":"","address":"","soumission_ref":"","project_description":"","property_type":"","suggested_service":"","suggested_price":0}
For suggested_service choose from: "Analyse structurale générale","Inspection et rapport structural","Avis d'expert — stabilisation et renforcement","Enlèvement de mur porteur","Inspection des fondations","Évaluation des fissures et désordres structuraux","Mur de soutènement","Conception structurale complète","Analyse structurale — sous-sol et ajout au-dessus du garage","Réaménagement intérieur avec modification structurale".
suggested_price: realistic CAD integer. ONLY JSON."""
    response = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":mime,"data":img_b64}},
            {"type":"text","text":prompt}
        ]}]
    )
    text = ''.join(b.text for b in response.content if hasattr(b,'text'))
    return json.loads(text.replace('```json','').replace('```','').strip())

# ── Flask Routes ─────────────────────────────────────────────────────
@app.route('/')
def index():
    with open(os.path.join(BASE, 'index.html'), 'r', encoding='utf-8') as f:
        return Response(f.read(), mimetype='text/html')

@app.route('/api/extract', methods=['POST'])
def api_extract():
    data = request.json
    info = extract_info(data.get('image'), data.get('mime','image/jpeg'))
    return jsonify(info)

@app.route('/api/generate-pdf', methods=['POST'])
def api_pdf():
    data = request.json
    buf = generate_pdf(data)
    filename = f"{data.get('odsNum','ODS')}_{data.get('name','client').replace(' ','-')}.pdf"
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=filename)

# ── Telegram Bot (Webhook) ───────────────────────────────────────────
@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    import requests as req
    data = request.json
    if not data:
        return 'ok'

    msg = data.get('message', {})
    callback = data.get('callback_query', {})
    chat_id = msg.get('chat', {}).get('id') or callback.get('message', {}).get('chat', {}).get('id')

    def send(text, keyboard=None):
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
        if keyboard:
            payload['reply_markup'] = {'inline_keyboard': keyboard}
        req.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage', json=payload)

    def send_file_tg(filepath, filename, caption):
        with open(filepath, 'rb') as f:
            req.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendDocument',
                data={'chat_id': chat_id, 'caption': caption},
                files={'document': (filename, f)})

    # Callback query
    if callback:
        uid = callback['from']['id']
        cdata = callback.get('data','')
        req.post(f'https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery',
                 json={'callback_query_id': callback['id']})

        if cdata == 'confirm_excel':
            d = user_data.get(uid)
            if not d:
                send("❌ Données introuvables. Envoyez une nouvelle photo.")
                return 'ok'
            try:
                send("⏳ Génération du fichier Excel...")
                out = generate_excel(d)
                fname = f"{d['odsNum']}_{d['name'].replace(' ','-')}.xlsx"
                send_file_tg(out, fname, f"✅ Excel généré!\n💰 ${d['price']:,} CAD")
                os.remove(out)
            except Exception as e:
                send(f"❌ Erreur: {str(e)}")

        elif cdata == 'confirm_pdf':
            d = user_data.get(uid)
            if not d:
                send("❌ Données introuvables.")
                return 'ok'
            try:
                send("⏳ Génération du PDF...")
                buf = generate_pdf(d)
                fname = f"{d['odsNum']}_{d['name'].replace(' ','-')}.pdf"
                buf.seek(0)
                import requests as req2
                req2.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendDocument',
                    data={'chat_id': chat_id, 'caption': f"✅ PDF généré!\n💰 ${d['price']:,} CAD"},
                    files={'document': (fname, buf)})
            except Exception as e:
                send(f"❌ Erreur: {str(e)}")

        elif cdata == 'change_price':
            user_data[uid] = user_data.get(uid, {})
            user_data[uid]['waiting_price'] = True
            send("💰 Entrez le nouveau prix (ex: 3500):")

        return 'ok'

    # Text message
    if msg.get('text'):
        uid = msg['from']['id']
        text = msg['text']

        if text == '/start':
            send("👋 *Bienvenue — Métra Structure*\n\n📸 Envoyez une photo du client\n(SoumissionRenovation, courriel, formulaire)")
            return 'ok'

        d = user_data.get(uid, {})
        if d.get('waiting_price'):
            try:
                price = int(text.strip().replace('$','').replace(',','').replace(' ',''))
                d['price'] = price
                d['waiting_price'] = False
                user_data[uid] = d
                keyboard = [
                    [{'text':'📊 Excel', 'callback_data':'confirm_excel'},
                     {'text':'📄 PDF', 'callback_data':'confirm_pdf'}],
                    [{'text':'✏️ Changer prix', 'callback_data':'change_price'}]
                ]
                send(f"💰 Prix mis à jour: ${price:,} CAD\n\nChoisissez le format:", keyboard)
            except:
                send("❌ Entrez un nombre valide (ex: 3500)")
        else:
            send("📸 Envoyez une photo du client pour commencer.")

    # Photo
    if msg.get('photo'):
        uid = msg['from']['id']
        send("🔍 Extraction des informations en cours...")
        try:
            photo = msg['photo'][-1]
            file_id = photo['file_id']
            import requests as req2
            r = req2.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}')
            fpath = r.json()['result']['file_path']
            img_r = req2.get(f'https://api.telegram.org/file/bot{BOT_TOKEN}/{fpath}')
            img_b64 = base64.b64encode(img_r.content).decode()

            info = extract_info(img_b64)
            yr = datetime.now().strftime('%y')
            ods_num = f"ODS{yr}-{random.randint(100,999)}"
            price = info.get('suggested_price') or PRICES.get(info.get('suggested_service',''), 3200)

            user_data[uid] = {
                'name': info.get('client_name',''),
                'phone': info.get('phone',''),
                'email': info.get('email',''),
                'addr': info.get('address',''),
                'ref': info.get('soumission_ref',''),
                'desc': info.get('project_description',''),
                'type': info.get('property_type',''),
                'service': info.get('suggested_service','Analyse structurale générale'),
                'price': price,
                'ods_num': ods_num,
                'odsNum': ods_num,
                'date': datetime.now().strftime('%Y-%m-%d'),
            }

            text = (
                f"✅ *Informations extraites*\n\n"
                f"👤 *Client:* {info.get('client_name','—')}\n"
                f"📍 *Adresse:* {info.get('address','—')}\n"
                f"📞 *Tél:* {info.get('phone','—')}\n"
                f"📧 *Courriel:* {info.get('email','—')}\n"
                f"🏠 *Type:* {info.get('property_type','—')}\n"
                f"🔢 *Réf:* {info.get('soumission_ref','—')}\n\n"
                f"🔧 *Service:* {info.get('suggested_service','—')}\n"
                f"💰 *Prix suggéré:* ${price:,} CAD\n"
                f"📄 *N° ODS:* {ods_num}\n\n"
                f"Choisissez le format:"
            )
            keyboard = [
                [{'text':'📊 Excel', 'callback_data':'confirm_excel'},
                 {'text':'📄 PDF', 'callback_data':'confirm_pdf'}],
                [{'text':'✏️ Changer prix', 'callback_data':'change_price'}]
            ]
            send(text, keyboard)
        except Exception as e:
            send(f"❌ Erreur: {str(e)}")

    return 'ok'

def setup_webhook():
    import requests as req
    import time
    time.sleep(3)
    url = os.environ.get('RAILWAY_PUBLIC_DOMAIN','')
    if url:
        webhook_url = f"https://{url}/webhook/{BOT_TOKEN}"
        r = req.post(f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook',
                     json={'url': webhook_url})
        logger.info(f"Webhook set: {r.json()}")

if __name__ == '__main__':
    t = threading.Thread(target=setup_webhook, daemon=True)
    t.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
