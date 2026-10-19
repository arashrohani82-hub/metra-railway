"""Preview and explicitly confirm Google review requests for completed projects."""
import os
import html
import base64
import re
import secrets
import sqlite3
import urllib.parse

import app as legacy
import ods_runtime

BUTTON = '⭐ Demander un avis Google'
DEFAULT_REVIEW_URL = 'https://search.google.com/local/writereview?placeid=ChIJT27dfZQVZw8RP7r7j40rv0A'
PREFIX = 'google_review:'
PAGE_SIZE = 15


def review_url():
    url = os.environ.get('GOOGLE_REVIEW_URL', DEFAULT_REVIEW_URL).strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('GOOGLE_REVIEW_URL must be an HTTPS URL')
    return url


def build_request(data, folder):
    name = legacy.normalize_client_name(data.get('name'))
    first_name = name.split()[0].strip(',;:') if name else ''
    brand = str(getattr(legacy, 'DISPLAY_BRAND', 'Metra Consultation'))
    if data.get('language') == 'en':
        greeting = f'Hello {first_name},' if first_name else 'Hello,'
        subject = 'A quick note following our work together'
        body = (f'{greeting}\n\nIt was a pleasure to help you with your project. '
                'Thank you for placing your trust in us.\n\n'
                'Would you take a moment to share your experience on Google? '
                'Your feedback would help other property owners choose their engineer '
                'with confidence and help more people discover our team.\n\n'
                f'Share my experience on Google:\n{review_url()}\n\n'
                'Thank you very much for your time. Please feel free to contact us '
                'with any questions; we would be happy to work with you again.'
                f'\n\nKind regards,\n\nArash Rohani, ing., P.Eng.\n'
                f'President – Structural and Civil Engineer\n{brand}\n'
                'a.rohani@metraconsultation.ca | (438) 867-4131\nmetraconsultation.ca')
    else:
        greeting = f'Bonjour {first_name},' if first_name else 'Bonjour,'
        subject = 'Un petit mot à la suite de notre collaboration'
        body = (f'{greeting}\n\nCe fut un plaisir de vous accompagner dans votre projet. '
                'Merci de nous avoir accordé votre confiance.\n\n'
                'Accepteriez-vous de consacrer un instant à partager votre expérience sur Google ? '
                'Votre témoignage aiderait d’autres propriétaires à choisir leur ingénieur '
                'en confiance et contribuerait à faire connaître notre équipe.\n\n'
                f'Partager mon expérience sur Google :\n{review_url()}\n\n'
                'Un grand merci pour votre temps. Nous restons à votre disposition pour toute '
                'question et serons heureux de vous accompagner à nouveau.'
                f'\n\nCordialement,\n\nArash Rohani, ing., P.Eng.\n'
                f'Président – Ingénieur en structure et génie civil\n{brand}\n'
                'a.rohani@metraconsultation.ca | (438) 867-4131\nmetraconsultation.ca')
    return subject, body


def request_email_html(body):
    # Reuse the same logo, signature, contact links and styling as ODS emails.
    formatted_body = body.replace('Partager mon expérience sur Google :\n', '').replace('Share my experience on Google:\n', '')
    markup = legacy.email_body_html(formatted_body)
    markup = markup.replace('Président – Ingénieur en structure</div>',
                            'Président – Ingénieur en structure et génie civil</div>')
    for line in str(body).splitlines():
        if line.startswith('https://'):
            escaped = html.escape(line.strip())
            label = 'Share my experience on Google' if 'Hello' in body.split('\n', 1)[0] else 'Partager mon expérience sur Google'
            markup = markup.replace(escaped, f'<a href="{escaped}" style="color:#1155cc;">{label}</a>', 1)
            break
    return markup


def build_review_email_message(pending, recipient):
    markup = request_email_html(pending['body'])
    markup, replaced = re.subn(r'src="[^"]*/assets/metra-logo\.png"',
                               'src="cid:metra-review-logo"', markup)
    message = {'subject': pending['subject'],
               'body': {'contentType': 'HTML', 'content': markup},
               'toRecipients': [{'emailAddress': {'address': recipient}}]}
    if replaced:
        with open(legacy.LOGOS['metra'], 'rb') as logo:
            content = base64.b64encode(logo.read()).decode('ascii')
        message['attachments'] = [{
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': 'metra-logo.png', 'contentType': 'image/png',
            'contentId': 'metra-review-logo', 'isInline': True,
            'contentBytes': content,
        }]
    return message


def show_projects(chat_id, uid):
    try:
        projects = ods_runtime.onedrive_projects()
    except Exception:
        legacy.logger.exception('Google review project listing failed')
        legacy.tg(chat_id, '❌ Impossible de consulter OneDrive. Réessayez plus tard.')
        return
    if not projects:
        legacy.tg(chat_id, 'Aucun projet trouvé pour l’année en cours.')
        return
    session = legacy.user_data.setdefault(uid, {})
    session['google_review_choices'] = {
        'token': secrets.token_hex(4),
        'folders': [str(p.get('name') or '') for p in projects],
    }
    legacy.save_user_data()
    show_page(chat_id, uid, 0)


def show_page(chat_id, uid, page):
    choices = legacy.user_data.get(uid, {}).get('google_review_choices') or {}
    folders = choices.get('folders') or []
    token = choices.get('token')
    if page < 0 or page * PAGE_SIZE >= len(folders):
        legacy.tg(chat_id, 'Sélection expirée. Ouvrez de nouveau « Demander un avis Google ».')
        return
    start = page * PAGE_SIZE
    rows = [[{'text': folder[:62], 'callback_data': f'{PREFIX}{token}:pick:{i}'}]
            for i, folder in enumerate(folders[start:start + PAGE_SIZE], start)]
    navigation = []
    for label, target, valid in [('◀️', page - 1, page > 0),
                                  ('▶️', page + 1, start + PAGE_SIZE < len(folders))]:
        if valid:
            navigation.append({'text': label, 'callback_data': f'{PREFIX}{token}:page:{target}'})
    if navigation:
        rows.append(navigation)
    legacy.tg(chat_id, '⭐ Demander un avis Google\n\nChoisissez un projet dont le mandat est terminé '
              '(année en cours). Vérifiez le message et le destinataire avant de confirmer l’envoi.', rows)


def prepare(chat_id, uid, index):
    choices = legacy.user_data.get(uid, {}).get('google_review_choices') or {}
    folders = choices.get('folders') or []
    if index < 0 or index >= len(folders):
        legacy.tg(chat_id, 'Projet introuvable. Ouvrez de nouveau « Demander un avis Google ».')
        return
    folder = folders[index]
    try:
        _, record = ods_runtime._find_history_by_project_folder(folder)
        data = dict((record or {}).get('data') or {})
        if not data.get('name') or not data.get('email'):
            recovered = ods_runtime.recover_project_metadata_from_onedrive(folder)
            for key, value in recovered.items():
                if not data.get(key) and value:
                    data[key] = value
        subject, body = build_request(data, folder)
        email = legacy.valid_client_email(data.get('email')) or 'à confirmer'
        nonce = secrets.token_hex(8)
        session = legacy.user_data.setdefault(uid, {})
        session['google_review_pending'] = {
            'nonce': nonce, 'folder': folder, 'recipient': email,
            'subject': subject, 'body': body,
        }
        legacy.save_user_data()
        legacy.tg(chat_id, f'⭐ Message prêt à copier\nProjet : {folder}\nCourriel : {email}\nObjet : {subject}')
        rows = [[{'text': '🌐 Ouvrir le lien Google', 'url': review_url()}]]
        if email != 'à confirmer':
            rows.append([{'text': '✅ Confirmer et envoyer par courriel',
                          'callback_data': f'{PREFIX}{nonce}:send:0'}])
        rows.append([{'text': '❌ Annuler l’envoi', 'callback_data': f'{PREFIX}{nonce}:cancel:0'}])
        # The approved body must be exactly what is sent, including client language.
        from proposal_language import LANGUAGE
        language_token = LANGUAGE.set('fr')
        try:
            legacy.tg(chat_id, body, rows)
        finally:
            LANGUAGE.reset(language_token)
    except Exception:
        legacy.logger.exception('Google review preparation failed')
        legacy.tg(chat_id, '❌ Impossible de préparer le message. Réessayez plus tard.')


def send_request(chat_id, uid, nonce):
    pending = dict(legacy.user_data.get(uid, {}).get('google_review_pending') or {})
    if not pending or not secrets.compare_digest(str(pending.get('nonce', '')), nonce):
        legacy.tg(chat_id, 'Aperçu expiré. Préparez de nouveau la demande.')
        return
    recipient = legacy.valid_client_email(pending.get('recipient'))
    if not recipient:
        legacy.tg(chat_id, '❌ Adresse courriel client manquante ou invalide.')
        return
    # Resolve credentials before claiming the send; never store tokens in the journal.
    try:
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        sender = urllib.parse.quote(config['EMAIL_SENDER'], safe='')
        message = build_review_email_message(pending, recipient)
    except Exception:
        legacy.logger.exception('Google review email configuration failed')
        legacy.tg(chat_id, '❌ Connexion Microsoft 365 impossible. Aucun courriel envoyé.')
        return
    folder = pending['folder']
    with sqlite3.connect(os.path.join(legacy.DATA_DIR, 'google_review_sends.sqlite3')) as db:
        db.execute('CREATE TABLE IF NOT EXISTS sends (project TEXT PRIMARY KEY, recipient TEXT, status TEXT)')
        result = db.execute('INSERT OR IGNORE INTO sends VALUES (?, ?, ?)', (folder, recipient, 'sending'))
        claimed = result.rowcount == 1
    if not claimed:
        legacy.tg(chat_id, '⚠️ Demande déjà envoyée ou en cours pour ce projet. Consultez les éléments envoyés avant toute nouvelle tentative.')
        return
    try:
        response = legacy.req.post(
            f'https://graph.microsoft.com/v1.0/users/{sender}/sendMail',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json={'message': message, 'saveToSentItems': True}, timeout=45,
        )
        if response.status_code != 202:
            raise RuntimeError(f'Microsoft 365 status {response.status_code}')
    except Exception:
        # Retain the durable claim after a timeout: delivery could have succeeded.
        legacy.logger.exception('Google review send not confirmed')
        legacy.tg(chat_id, '⚠️ Envoi non confirmé. Vérifiez les éléments envoyés Microsoft 365 ; aucune nouvelle tentative automatique.')
        return
    with sqlite3.connect(os.path.join(legacy.DATA_DIR, 'google_review_sends.sqlite3')) as db:
        db.execute('UPDATE sends SET status = ? WHERE project = ?', ('sent', folder))
    legacy.user_data.get(uid, {}).pop('google_review_pending', None)
    legacy.save_user_data()
    legacy.tg(chat_id, f'✅ Demande d’avis acceptée par Microsoft 365 pour {recipient}.')


def handle(update):
    callback = (update or {}).get('callback_query') or {}
    message = callback.get('message') or (update or {}).get('message') or {}
    cdata = str(callback.get('data') or '')
    if str(message.get('text') or '').strip() != BUTTON and not cdata.startswith(PREFIX):
        return False
    actor = callback.get('from') or message.get('from') or {}
    chat_id = (message.get('chat') or {}).get('id')
    if actor.get('id') not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id, '⛔ Ce bot est privé.')
        return True
    uid = str(actor.get('id'))
    if not callback:
        show_projects(chat_id, uid)
        return True
    try:
        legacy.req.post(f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                        json={'callback_query_id': callback.get('id')}, timeout=10)
    except Exception:
        pass
    parts = cdata.split(':')
    if len(parts) == 4 and parts[2] in ('send', 'cancel'):
        pending = legacy.user_data.get(uid, {}).get('google_review_pending') or {}
        if parts[1] != pending.get('nonce'):
            legacy.tg(chat_id, 'Aperçu expiré. Préparez de nouveau la demande.')
        elif parts[2] == 'send':
            send_request(chat_id, uid, parts[1])
        else:
            legacy.user_data[uid].pop('google_review_pending', None)
            legacy.save_user_data()
            legacy.tg(chat_id, '✅ Envoi annulé.')
        return True
    choices = legacy.user_data.get(uid, {}).get('google_review_choices') or {}
    if len(parts) != 4 or parts[1] != choices.get('token') or not parts[3].isdigit():
        legacy.tg(chat_id, 'Sélection expirée. Ouvrez de nouveau « Demander un avis Google ».')
        return True
    if parts[2] == 'page':
        show_page(chat_id, uid, int(parts[3]))
    elif parts[2] == 'pick':
        prepare(chat_id, uid, int(parts[3]))
    return True


def install_menu():
    previous = legacy.main_menu

    def menu():
        result = previous()
        rows = result.setdefault('keyboard', [])
        if not any(cell.get('text') == BUTTON for row in rows for cell in row):
            rows.append([{'text': BUTTON}])
        return result

    legacy.main_menu = menu

