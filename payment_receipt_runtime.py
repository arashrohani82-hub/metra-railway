"""Manual, confirmed receipt workflow for issued project invoices."""
import base64
import io
import json
import os
import re
import threading
import urllib.parse
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import invoice_control_runtime as control
from payment_receipts import invoice_details, money, parse_amount, payment_balance, validate_payment, receipt_pdf

legacy = control.legacy
LOCK = threading.RLock()
LEDGER = os.path.join(legacy.DATA_DIR, 'payment_receipts.json')
METHODS = ('Interac', 'Virement bancaire', 'Chèque encaissé', 'Carte', 'Espèces', 'Autre')


def today():
    return datetime.now(ZoneInfo('America/Toronto')).date()


def ledger():
    if not os.path.exists(LEDGER):
        return {}
    with open(LEDGER, encoding='utf-8') as f:
        records = json.load(f)
    if not isinstance(records, dict):
        raise ValueError('Registre des paiements invalide')
    return records


def save_ledger(records):
    temporary = LEDGER + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, LEDGER)


def invoice_records(invoice, records=None):
    records = ledger() if records is None else records
    return [r for r in records.values() if r['invoice']['filename'] == invoice['filename']]


def save_session(uid):
    legacy.save_user_data()


def show_invoices(chat_id, uid):
    data = legacy.user_data.get(uid, {})
    if not data.get('project_folder'):
        legacy.tg(chat_id, '⚠️ Sélectionnez le projet dans Facturation.')
        return
    token = legacy.graph_access_token()
    project_match = re.search(r'P\d{2}-\d{3}-[A-Z0-9]{2,5}', data['project_folder'], re.I)
    if not project_match:
        raise ValueError('Code du projet introuvable')
    project = project_match.group(0).upper()
    choices = {}
    for item in legacy.list_onedrive_children(token, legacy.INVOICE_DRIVE_OWNER, legacy.INVOICE_FOLDER):
        filename = item.get('name') or ''
        if not filename.lower().endswith('.pdf') or not filename.upper().startswith('FAC'):
            continue
        # Standard invoice names carry the project reference. Legacy names are
        # still checked using the actual PDF rather than assumed from a session.
        if re.search(r'P\d{2}-\d{3}-[A-Z0-9]+', filename, re.I) and project not in filename.upper():
            continue
        path = item.get('_receipt_path') or f'{legacy.INVOICE_FOLDER}/{filename}'
        content = legacy.download_onedrive_path(token, legacy.INVOICE_DRIVE_OWNER, path)
        text = control._pdf_text(content)
        if project not in re.sub(r'\s+', '', text).upper():
            continue
        details = invoice_details(text, filename)
        details['path'] = path
        _, balance = payment_balance(details, invoice_records(details))
        details['remaining'] = str(balance)
        choices[str(len(choices)+1)] = details
    data['payment_choices'] = choices
    data.pop('payment_pending', None)
    data.pop('payment_waiting', None)
    save_session(uid)
    buttons = [[{'text': f"{v['filename']} | solde {money(v['remaining']):.2f} $", 'callback_data': 'pay_pick:'+k}]
               for k,v in choices.items()]
    buttons.append([{'text':'❌ Annuler','callback_data':'pay_cancel'}])
    legacy.tg(chat_id, '💳 Réception d’un paiement\n\nChoisissez la facture. '
              'Le solde tient compte des paiements enregistrés dans ce bot.' if choices else
              'Aucune facture PDF trouvée pour ce projet.', buttons)


def show_amount(chat_id, uid, invoice):
    _, remaining = payment_balance(invoice, invoice_records(invoice))
    if remaining <= 0:
        legacy.tg(chat_id, '✅ Cette facture est déjà acquittée selon le registre du bot.')
        return
    data = legacy.user_data[uid]
    data['payment_pending'] = {'key': uuid.uuid4().hex, 'invoice': invoice,
                               'project_folder':data['project_folder'], 'date':today().isoformat()}
    save_session(uid)
    legacy.tg(chat_id, f"Facture : {invoice['filename']}\nClient : {invoice['client']}\n"
              f'Solde enregistré : {remaining:.2f} $\n\nQuel montant avez-vous réellement reçu (taxes incluses)?', [
              [{'text':'✅ Solde complet','callback_data':'pay_full'}],
              [{'text':'✏️ Montant reçu / paiement partiel','callback_data':'pay_amount'}],
              [{'text':'❌ Annuler','callback_data':'pay_cancel'}]])


def show_methods(chat_id, uid):
    legacy.tg(chat_id, 'Quel est le mode du paiement reçu?',
              [[{'text':m,'callback_data':f'pay_method:{i}'}] for i,m in enumerate(METHODS)])


def show_confirmation(chat_id, uid):
    pending = legacy.user_data[uid]['payment_pending']
    invoice = pending['invoice']
    paid, _ = payment_balance(invoice, invoice_records(invoice))
    amount = validate_payment(invoice, invoice_records(invoice), pending['amount'])
    remaining = money(invoice['total']) - paid - amount
    legacy.tg(chat_id, f"🧾 Confirmation du paiement reçu\n\nFacture : {invoice['filename']}\n"
              f"Client : {invoice['client']}\nMontant reçu : {amount:.2f} $\n"
              f"Date : {pending['date']}\nMode : {pending['method']}\n"
              f"Solde après paiement : {remaining:.2f} $\n\n"
              'Confirmez uniquement après réception effective des fonds. Le reçu sera créé; '
              'vous pourrez ensuite choisir de l’envoyer au client.', [
              [{'text':'✅ Fonds reçus - créer le reçu','callback_data':'pay_confirm:'+pending['key']}],
              [{'text':'📅 Modifier la date','callback_data':'pay_date'}],
              [{'text':'❌ Annuler','callback_data':'pay_cancel'}]])


def issue_receipt(chat_id, uid, key):
    with LOCK:
        records = ledger()
        data = legacy.user_data.get(uid,{})
        pending = data.get('payment_pending') or {}
        record = records.get(key)
        if not record:
            if pending.get('key') != key or not pending.get('method') or not pending.get('amount'):
                raise ValueError('Confirmation expirée. Ouvrez de nouveau Réception d’un paiement.')
            amount = validate_payment(pending['invoice'], invoice_records(pending['invoice'],records), pending['amount'])
            paid,_ = payment_balance(pending['invoice'], invoice_records(pending['invoice'],records))
            record = {**pending, 'uid':uid, 'amount':str(amount), 'cumulative':str(paid+amount),
                      'remaining':str(money(pending['invoice']['total'])-paid-amount),
                      'id':f"REC{today().year % 100:02d}-{pending['invoice']['number']}-{key[:12].upper()}",
                      'archive_year':str(today().year), 'archived':False, 'emailed':False}
            records[key] = record
            # Commit locally before network calls. Retries reuse the same receipt
            # and cannot count the payment a second time, even after a restart.
            save_ledger(records)
        if record['uid'] != uid:
            raise ValueError('Ce reçu appartient à une autre session.')
        pdf = receipt_pdf(record)
        filename = record['id']+'.pdf'
        token = legacy.graph_access_token()
        root = f"Metra Structure Inc/Financial/Recus/{record['archive_year']}"
        if not record['archived']:
            legacy.create_onedrive_folder(token,legacy.INVOICE_DRIVE_OWNER,'Metra Structure Inc/Financial','Recus')
            legacy.create_onedrive_folder(token,legacy.INVOICE_DRIVE_OWNER,'Metra Structure Inc/Financial/Recus',record['archive_year'])
            legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,f'{root}/{filename}',pdf,'application/pdf')
            legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,f"{root}/{record['id']}.json",
                                        json.dumps(record,ensure_ascii=False).encode(),'application/json')
            record['archived'] = True
            save_ledger(records)
        project_year = '20'+re.search(r'P(\d{2})-',record['project_folder']).group(1)
        try:
            legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,
                f"Metra Structure Inc/Projects/{project_year}/{record['project_folder']}/Correspondence/{filename}",pdf,'application/pdf')
        except Exception:
            legacy.tg(chat_id,'⚠️ Reçu conservé dans Financial; copie dans le dossier projet non disponible.')
        if (data.get('payment_pending') or {}).get('key') == key:
            data.pop('payment_pending',None)
            data.pop('payment_waiting',None)
            save_session(uid)
        legacy.tg_doc(chat_id,io.BytesIO(pdf),filename,'✅ Réception enregistrée. Reçu de paiement.')
        legacy.tg(chat_id,f"Reçu : {record['id']}\nSolde : {money(record['remaining']):.2f} $", [
            [{'text':'📧 Envoyer le reçu au client','callback_data':'pay_email:'+key}]])


def send_receipt(chat_id, uid, key):
    with LOCK:
        records=ledger()
        record=records.get(key)
        if not record or record['uid']!=uid or not record['archived']:
            raise ValueError('Reçu introuvable ou non archivé')
        if record['emailed']:
            legacy.tg(chat_id,'✅ Ce reçu a déjà été envoyé au client.')
            return
        email=legacy.valid_client_email(record['invoice']['email'])
        if not email:
            raise ValueError('Courriel absent de la facture. Téléchargez le reçu et envoyez-le manuellement.')
        sender=urllib.parse.quote(legacy.INVOICE_EMAIL_SENDER,safe='')
        body={'message':{'subject':'Reçu de paiement - '+record['invoice']['filename'],
            'body':{'contentType':'Text','content':f"Bonjour {record['invoice']['client']},\n\n"
                f"Nous confirmons la réception de {money(record['amount']):.2f} $ le {record['date']} "
                f"pour la facture {record['invoice']['filename']}.\n"
                f"Solde de cette facture : {money(record['remaining']):.2f} $.\n\n"
                'Veuillez trouver le reçu en pièce jointe. Merci de votre confiance.\n\nMetra Consultation Inc.'},
            'toRecipients':[{'emailAddress':{'address':email}}],
            'attachments':[{'@odata.type':'#microsoft.graph.fileAttachment','name':record['id']+'.pdf',
                'contentType':'application/pdf','contentBytes':base64.b64encode(receipt_pdf(record)).decode()}]},
              'saveToSentItems':True}
        response=legacy.req.post(f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
            headers={'Authorization':'Bearer '+legacy.graph_access_token(),'Content-Type':'application/json'},json=body,timeout=45)
        if response.status_code!=202:
            raise ValueError(f'Envoi du reçu non confirmé ({response.status_code})')
        record['emailed']=True
        save_ledger(records)
        legacy.tg(chat_id,'✅ Reçu envoyé à '+email)


def handle_update(update):
    cb=update.get('callback_query') or {}
    msg=update.get('message') or {}
    actor=(cb.get('from') or msg.get('from') or {}).get('id')
    uid=str(actor)
    data=legacy.user_data.get(uid,{})
    action=cb.get('data') or ''
    text=str(msg.get('text') or '').strip()
    waiting=data.get('payment_waiting')
    active=action.startswith('pay_') or bool(waiting and msg)
    if not active:
        return False
    chat_id=((cb.get('message') or msg).get('chat') or {}).get('id')
    if actor not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id,'⛔ Ce bot est privé.')
        return True
    if msg and (text.startswith('/') or text in ('❌ Annuler','🧾 Facturation','🧾 Facturer un projet',
        '📝 Nouvelle offre','📬 Suivi offres','📊 Tableau de bord','📁 Convertir une offre en projet','❓ Aide')):
        data.pop('payment_waiting',None)
        data.pop('payment_pending',None)
        save_session(uid)
        return False
    try:
        if cb:
            try:
                legacy.req.post(f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                                json={'callback_query_id':cb.get('id')},timeout=3)
            except Exception:
                pass
        if action=='pay_start':
            show_invoices(chat_id,uid)
        elif action=='pay_cancel':
            key=(data.get('payment_pending') or {}).get('key')
            if key and key in ledger():
                legacy.tg(chat_id,'Le paiement est déjà enregistré. Réessayez la création du même reçu.',
                    [[{'text':'🔄 Réessayer le reçu','callback_data':'pay_confirm:'+key}]])
                return True
            data.pop('payment_waiting',None)
            data.pop('payment_pending',None)
            save_session(uid)
            legacy.tg(chat_id,'Réception annulée. Aucun nouveau paiement enregistré.')
        elif action.startswith('pay_pick:'):
            invoice=(data.get('payment_choices') or {}).get(action.split(':',1)[1])
            if not invoice: raise ValueError('Facture introuvable. Recommencez.')
            show_amount(chat_id,uid,invoice)
        elif action.startswith('pay_confirm:'):
            issue_receipt(chat_id,uid,action.split(':',1)[1])
        elif action.startswith('pay_email:'):
            send_receipt(chat_id,uid,action.split(':',1)[1])
        else:
            pending=data.get('payment_pending') or {}
            if not pending: raise ValueError('Ouvrez de nouveau Réception d’un paiement.')
            if action=='pay_full':
                _,remaining=payment_balance(pending['invoice'],invoice_records(pending['invoice']))
                pending['amount']=str(validate_payment(pending['invoice'],invoice_records(pending['invoice']),remaining))
                save_session(uid)
                show_methods(chat_id,uid)
            elif action in ('pay_amount','pay_date'):
                data['payment_waiting']='amount' if action=='pay_amount' else 'date'
                save_session(uid)
                legacy.tg(chat_id,'Entrez le montant reçu (taxes incluses).' if action=='pay_amount' else 'Date de réception réelle : AAAA-MM-JJ')
            elif action.startswith('pay_method:'):
                method=int(action.split(':',1)[1])
                if not 0<=method<len(METHODS): raise ValueError('Mode invalide')
                pending['method']=METHODS[method]
                save_session(uid)
                show_confirmation(chat_id,uid)
            elif msg and waiting:
                if waiting=='amount':
                    pending['amount']=str(validate_payment(pending['invoice'],invoice_records(pending['invoice']),parse_amount(text)))
                else:
                    try:
                        received=datetime.strptime(text,'%Y-%m-%d').date()
                    except ValueError as exc:
                        raise ValueError('Date invalide. Format : AAAA-MM-JJ') from exc
                    if received>today(): raise ValueError('La date ne peut pas être dans le futur')
                    pending['date']=received.isoformat()
                data.pop('payment_waiting',None)
                save_session(uid)
                show_methods(chat_id,uid) if waiting=='amount' else show_confirmation(chat_id,uid)
    except Exception as exc:
        legacy.logger.exception('Payment receipt workflow failed')
        legacy.tg(chat_id,'❌ '+str(exc)+'\nSi le paiement a été confirmé, réutilisez le même bouton de confirmation pour réessayer sans doublon.')
    return True


legacy.logger.info('PAYMENT RECEIPT WORKFLOW ACTIVE')
