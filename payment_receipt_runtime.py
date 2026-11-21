"""Confirmed invoice payments and internal project cash entries."""
import base64
import io
import json
import os
import re
import threading
import urllib.parse
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import invoice_control_runtime as control
from ods_runtime import confirmed_project_client
from payment_receipts import invoice_details, money, parse_amount, payment_balance, split_payment, receipt_pdf

legacy = control.legacy
LOCK = threading.RLock()
LEDGER = os.path.join(legacy.DATA_DIR, 'payment_receipts.json')
SELECTIONS = os.path.join(legacy.DATA_DIR, 'payment_invoice_selections.json')
CASH = 'Espèces'
METHODS = ('Interac', 'Virement bancaire', 'Chèque encaissé', 'Carte', CASH, 'Autre')
INVOICE_NET_CACHE = {}


def project_received_fractions(contracts):
    """Compute the portion of each contract already collected.

    Invoice payments contribute their pre-tax share. Cash recorded directly
    against a project is applied at its recorded amount, without an invoice.
    """
    grouped = {}
    for record in ledger().values():
        match = re.match(r'P\d{2}-\d{3}(?!\d)', record.get('project_folder', ''), re.I)
        project_cash = record.get('accounting_only') and record.get('method') == CASH
        if match and match.group(0).upper() in contracts and (record.get('invoice') or project_cash):
            grouped.setdefault(match.group(0).upper(), []).append(record)
    result = {}
    token = None
    for code, records in grouped.items():
        try:
            contract = money(contracts[code])
            if contract <= 0:
                continue
            net_paid = Decimal('0.00')
            for record in records:
                invoice = record.get('invoice')
                if not invoice:
                    net_paid += money(record['received'])
                    continue
                path = invoice.get('path') or f"{legacy.INVOICE_FOLDER}/{invoice['filename']}"
                cache_key = (path, invoice['total'])
                with LOCK:
                    net_total = INVOICE_NET_CACHE.get(cache_key)
                if net_total is None:
                    token = token or legacy.graph_access_token()
                    pdf = legacy.download_onedrive_path(token, legacy.INVOICE_DRIVE_OWNER, path)
                    text = control._pdf_text(pdf)
                    if code not in re.sub(r'\s+', '', text).upper():
                        raise ValueError('Projet de la facture différent du reçu')
                    match = re.search(r'Sous[- ]total\s*:\s*\$?\s*([\d ,]+[.,]\d{2})', text, re.I)
                    if not match:
                        raise ValueError('Sous-total de facture introuvable')
                    net_total = parse_amount(match.group(1))
                    details = invoice_details(text, invoice['filename'])
                    if money(details['total']) != money(invoice['total']) or net_total <= 0:
                        raise ValueError('Montants de la facture modifiés')
                    with LOCK:
                        INVOICE_NET_CACHE[cache_key] = net_total
                net_paid += (money(record['amount']) * net_total / money(invoice['total']))
            # Invoice totals include rounded taxes; round the recovered net sum
            # to cents before comparing with the tax-exclusive contract amount.
            result[code] = min(1.0, float(money(net_paid) / contract))
        except Exception:
            legacy.logger.exception('Cannot reconcile received percentage for %s', code)
    return result


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
    return [r for r in records.values() if (r.get('invoice') or {}).get('filename') == invoice['filename']]


def save_session(uid):
    legacy.save_user_data()


def remember_invoices(uid, project_folder, choices):
    """Keep displayed invoice identities independent of mutable ODS sessions."""
    with LOCK:
        records = {}
        if os.path.exists(SELECTIONS):
            with open(SELECTIONS, encoding='utf-8') as f:
                records = json.load(f)
        user = records.setdefault(str(uid), {})
        for key, invoice in choices.items():
            user[key] = {'invoice': invoice, 'project_folder': project_folder}
        temporary = SELECTIONS + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, SELECTIONS)


def selected_invoice(uid, key):
    with LOCK:
        if os.path.exists(SELECTIONS):
            with open(SELECTIONS, encoding='utf-8') as f:
                selection = json.load(f).get(str(uid), {}).get(key)
            if selection:
                return selection
        # Legacy numeric indexes cannot identify an invoice after another list
        # has replaced the session. Expire them rather than pick the wrong PDF.
    return None


def show_invoices(chat_id, uid):
    data = legacy.user_data.get(uid, {})
    if not data.get('project_folder'):
        legacy.tg(chat_id, '⚠️ Sélectionnez le projet dans Facturation.')
        return
    token = legacy.graph_access_token()
    # Some legacy folders contain an empty discipline segment, e.g.
    # P26-034-_STR_XWW. The numeric project reference is still valid.
    project_match = re.search(r'P\d{2}-\d{3}(?!\d)(?:-[A-Z0-9]{2,5})?', data['project_folder'], re.I)
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
        if not re.search(re.escape(project) + r'(?![A-Z0-9])', re.sub(r'\s+', '', text), re.I):
            continue
        details = invoice_details(text, filename)
        details['path'] = path
        _, balance = payment_balance(details, invoice_records(details))
        if balance <= 0:
            continue
        details['remaining'] = str(balance)
        choices[uuid.uuid4().hex[:16]] = details
    remember_invoices(uid, data['project_folder'], choices)
    data['payment_choices'] = choices
    data.pop('payment_pending', None)
    data.pop('payment_waiting', None)
    save_session(uid)
    buttons = [[{'text': f"{v['filename']} | solde {money(v['remaining']):.2f} $", 'callback_data': 'pay_pick:'+k}]
               for k,v in choices.items()]
    buttons.append([{'text':'❌ Annuler','callback_data':'pay_cancel'}])
    legacy.tg(chat_id, '💳 Réception d’un paiement\n\nChoisissez la facture. '
              'Le solde tient compte des paiements enregistrés dans ce bot.' if choices else
              'Aucune facture avec un solde à recevoir pour ce projet.', buttons)


def show_amount(chat_id, uid, invoice, project_folder=None):
    _, remaining = payment_balance(invoice, invoice_records(invoice))
    if remaining <= 0:
        legacy.tg(chat_id, '✅ Cette facture est déjà acquittée selon le registre du bot.')
        return
    data = legacy.user_data.setdefault(uid, {})
    folder = project_folder or data['project_folder']
    client = confirmed_project_client(folder) or invoice['client']
    data['payment_pending'] = {'key': uuid.uuid4().hex, 'invoice': invoice,
                               'project_folder': folder, 'date': today().isoformat()}
    save_session(uid)
    legacy.tg(chat_id, f"Facture : {invoice['filename']}\nClient du projet : {client}\n"
              f'Solde enregistré : {remaining:.2f} $\n\nQuel montant avez-vous réellement reçu (taxes incluses)?', [
              [{'text':'✅ Solde complet','callback_data':'pay_full'}],
              [{'text':'✏️ Autre montant reçu','callback_data':'pay_amount'}],
              [{'text':'❌ Annuler','callback_data':'pay_cancel'}]])


def show_project_cash(chat_id, uid, folder, client):
    data = legacy.user_data[uid]
    data['payment_pending'] = {'key': uuid.uuid4().hex, 'project_folder': folder,
                               'client': confirmed_project_client(folder) or client or '',
                               'method': CASH, 'date': today().isoformat()}
    data['payment_waiting'] = 'amount'
    save_session(uid)
    legacy.tg(chat_id, f"💵 Encaissement en espèces · comptabilité\n{folder}\n\n"
              "Entrez le montant réellement reçu (ex. 400,00).",
              [[{'text': '❌ Annuler', 'callback_data': 'pay_cancel'}]])


def show_methods(chat_id, uid):
    legacy.tg(chat_id, 'Quel est le mode du paiement reçu?',
              [[{'text': 'Espèces · comptabilité' if method == CASH else method,
                 'callback_data': f'pay_method:{i}'}] for i, method in enumerate(METHODS)])


def credit_summary(applied, credit):
    if not credit:
        return ''
    return f"Imputé à cette facture : {applied:.2f} $\nCrédit client non imputé : {credit:.2f} $\n"


def show_confirmation(chat_id, uid):
    pending = legacy.user_data[uid]['payment_pending']
    invoice = pending.get('invoice')
    with LOCK:
        if pending['key'] in ledger():
            raise ValueError('Le paiement est déjà enregistré. Réessayez la création du même reçu.')
        received = money(pending['amount'])
        invoice_summary = ''
        if invoice:
            _, balance = payment_balance(invoice, invoice_records(invoice))
            received, applied, credit = split_payment(received, balance)
            pending['confirmed_balance'] = str(balance)
            invoice_summary = (credit_summary(applied, credit)
                               + f"Solde après paiement : {balance - applied:.2f} $\n")
        key = pending['key'] = uuid.uuid4().hex
        save_session(uid)
    accounting_only = pending['method'] == CASH
    folder = pending['project_folder']
    client = confirmed_project_client(folder) or (invoice['client'] if invoice else pending['client'])
    subject = f"Facture : {invoice['filename']}" if invoice else f"Projet : {folder}"
    client_line = f"Client du projet : {client}\n" if client else ''
    action = '✅ Fonds reçus - enregistrer' if accounting_only else '✅ Fonds reçus - créer le reçu'
    note = ('Le paiement sera enregistré en comptabilité.' if accounting_only else
            'Le reçu sera créé. Vous pourrez ensuite choisir de l’envoyer au client.')
    legacy.tg(chat_id, f"🧾 Confirmation du paiement reçu\n\n{subject}\n"
              f"{client_line}Montant reçu : {received:.2f} $\n"
              f"Date : {pending['date']}\nMode : {pending['method']}\n"
              f"{invoice_summary}\nConfirmez uniquement après réception effective des fonds. {note}", [
              [{'text': action, 'callback_data': 'pay_confirm:'+key}],
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
            if pending.get('invoice'):
                paid, balance = payment_balance(pending['invoice'], invoice_records(pending['invoice'], records))
                received, applied, credit = split_payment(pending['amount'], balance)
                confirmed_balance = pending.get('confirmed_balance')
                if (confirmed_balance is not None and money(confirmed_balance) != balance) or (
                    confirmed_balance is None and credit
                ):
                    raise ValueError('Le solde de la facture a changé. Ouvrez de nouveau Réception d’un paiement.')
                client = confirmed_project_client(pending['project_folder']) or pending['invoice']['client']
                record = {**pending, 'uid':uid, 'client': client, 'accounting_only': pending['method'] == CASH,
                          'received':str(received), 'amount':str(applied),
                          'credit':str(credit), 'cumulative':str(paid+applied), 'remaining':str(balance-applied),
                          'id':f"REC{today().year % 100:02d}-{pending['invoice']['number']}-{key[:12].upper()}",
                          'archive_year':str(today().year), 'archived':False, 'emailed':False}
            else:
                received = money(pending['amount'])
                if pending['method'] != CASH or received <= 0:
                    raise ValueError('Encaissement en espèces invalide.')
                year = today().year
                record = {**pending, 'uid': uid, 'accounting_only': True, 'received': str(received),
                          'id': f"ENC{year % 100:02d}-{key[:12].upper()}",
                          'archive_year': str(year), 'archived': False, 'emailed': False}
            records[key] = record
            # Commit locally before network calls. Retries reuse the same receipt
            # and cannot count the payment a second time, even after a restart.
            save_ledger(records)
        if record['uid'] != uid:
            raise ValueError('Ce reçu appartient à une autre session.')
        accounting_only = record.get('accounting_only', False)
        pdf = None if accounting_only else receipt_pdf(record)
        filename = record['id']+'.pdf'
        token = legacy.graph_access_token() if pdf is not None or not record['archived'] else None
        root = f"Metra Structure Inc/Financial/Recus/{record['archive_year']}"
        if not record['archived']:
            legacy.create_onedrive_folder(token,legacy.INVOICE_DRIVE_OWNER,'Metra Structure Inc/Financial','Recus')
            legacy.create_onedrive_folder(token,legacy.INVOICE_DRIVE_OWNER,'Metra Structure Inc/Financial/Recus',record['archive_year'])
            if pdf is not None:
                legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,f'{root}/{filename}',pdf,'application/pdf')
            legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,f"{root}/{record['id']}.json",
                                        json.dumps(record,ensure_ascii=False).encode(),'application/json')
            record['archived'] = True
            save_ledger(records)
        if (data.get('payment_pending') or {}).get('key') == key:
            data.pop('payment_pending',None)
            data.pop('payment_waiting',None)
            save_session(uid)
        if not record.get('invoice'):
            total = sum((money(r['received']) for r in records.values()
                         if not r.get('invoice') and r['project_folder'] == record['project_folder']),
                        Decimal('0.00'))
            legacy.tg(chat_id, f"✅ Encaissement en espèces enregistré.\n"
                      f"Projet : {record['project_folder']}\n"
                      f"Montant reçu : {money(record['received']):.2f} $\n"
                      f"Total en espèces sans facture : {total:.2f} $\nRéférence : {record['id']}")
            return
        if accounting_only:
            legacy.tg(chat_id, f"✅ Paiement en espèces enregistré en comptabilité.\n"
                      f"Client : {record['client']}\n"
                      f"Montant reçu : {money(record['received']):.2f} $\n"
                      + credit_summary(money(record['amount']), money(record['credit']))
                      + f"Solde : {money(record['remaining']):.2f} $")
            return
        project_year = '20'+re.search(r'P(\d{2})-',record['project_folder']).group(1)
        try:
            legacy.upload_onedrive_path(token,legacy.INVOICE_DRIVE_OWNER,
                f"Metra Structure Inc/Projects/{project_year}/{record['project_folder']}/Correspondence/{filename}",pdf,'application/pdf')
        except Exception:
            legacy.tg(chat_id,'⚠️ Reçu conservé dans Financial; copie dans le dossier projet non disponible.')
        legacy.tg_doc(chat_id,io.BytesIO(pdf),filename,'✅ Réception enregistrée. Reçu de paiement.')
        legacy.tg(chat_id,f"Reçu : {record['id']}\n"
                  + credit_summary(money(record['amount']), money(record.get('credit', 0)))
                  + f"Solde : {money(record['remaining']):.2f} $", [
            [{'text':'📧 Envoyer le reçu au client','callback_data':'pay_email:'+key}]])


def send_receipt(chat_id, uid, key):
    with LOCK:
        records=ledger()
        record=records.get(key)
        if not record or record['uid']!=uid or not record['archived']:
            raise ValueError('Reçu introuvable ou non archivé')
        if record.get('accounting_only'):
            raise ValueError('Ce paiement est réservé à la comptabilité.')
        client = confirmed_project_client(record['project_folder'])
        if client and legacy.normalize_client_name(record['invoice']['client']).casefold() != client.casefold():
            raise ValueError('Vérifiez le destinataire indiqué sur la facture avant tout envoi.')
        if record['emailed']:
            legacy.tg(chat_id,'✅ Ce reçu a déjà été envoyé au client.')
            return
        email=legacy.valid_client_email(record['invoice']['email'])
        if not email:
            raise ValueError('Courriel absent de la facture. Téléchargez le reçu et envoyez-le manuellement.')
        sender=urllib.parse.quote(legacy.INVOICE_EMAIL_SENDER,safe='')
        body={'message':{'subject':'Reçu de paiement - '+record['invoice']['filename'],
            'body':{'contentType':'Text','content':f"Bonjour {record['invoice']['client']},\n\n"
                f"Nous confirmons la réception de {money(record.get('received', record['amount'])):.2f} $ le {record['date']}.\n"
                f"Facture : {record['invoice']['filename']}.\n"
                + credit_summary(money(record['amount']), money(record.get('credit', 0)))
                + f"Solde de cette facture : {money(record['remaining']):.2f} $.\n\n"
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
            selection=selected_invoice(uid,action.split(':',1)[1])
            if not selection or not selection.get('project_folder'):
                legacy.tg(chat_id,'⚠️ Cette ancienne liste a expiré. Sélectionnez le projet dans Facturation puis Réception d’un paiement. Aucun paiement enregistré.')
                return True
            show_amount(chat_id,uid,selection['invoice'],selection['project_folder'])
        elif action.startswith('pay_confirm:'):
            issue_receipt(chat_id,uid,action.split(':',1)[1])
        elif action.startswith('pay_email:'):
            send_receipt(chat_id,uid,action.split(':',1)[1])
        else:
            pending=data.get('payment_pending') or {}
            if not pending: raise ValueError('Ouvrez de nouveau Réception d’un paiement.')
            if pending['key'] in ledger():
                raise ValueError('Le paiement est déjà enregistré. Réessayez la création du même reçu.')
            if not pending.get('invoice') and (action in ('pay_full', 'pay_amount') or action.startswith('pay_method:')):
                raise ValueError('Ce bouton appartient à un autre encaissement.')
            if action=='pay_full':
                _,remaining=payment_balance(pending['invoice'],invoice_records(pending['invoice']))
                received, _, _ = split_payment(remaining, remaining)
                pending.update(amount=str(received), key=uuid.uuid4().hex)
                pending.pop('confirmed_balance', None)
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
                    received = parse_amount(text)
                    invoice = pending.get('invoice')
                    if invoice:
                        _, remaining = payment_balance(invoice, invoice_records(invoice))
                        received, _, _ = split_payment(received, remaining)
                    elif received <= 0:
                        raise ValueError('Entrez un montant supérieur à zéro.')
                    pending.update(amount=str(received), key=uuid.uuid4().hex)
                    pending.pop('confirmed_balance', None)
                else:
                    try:
                        received=datetime.strptime(text,'%Y-%m-%d').date()
                    except ValueError as exc:
                        raise ValueError('Date invalide. Format : AAAA-MM-JJ') from exc
                    if received>today(): raise ValueError('La date ne peut pas être dans le futur')
                    pending['date']=received.isoformat()
                data.pop('payment_waiting',None)
                save_session(uid)
                if waiting == 'amount' and pending.get('invoice'):
                    show_methods(chat_id, uid)
                else:
                    show_confirmation(chat_id, uid)
    except Exception as exc:
        legacy.logger.exception('Payment receipt workflow failed')
        legacy.tg(chat_id,'❌ '+str(exc)+'\nSi le paiement a été confirmé, réutilisez le même bouton de confirmation pour réessayer sans doublon.')
    return True


legacy.logger.info('PAYMENT RECEIPT WORKFLOW ACTIVE')
