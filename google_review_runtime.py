"""Prepare Google review requests for completed projects without sending mail."""
import os
import secrets
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
    name = str(data.get('name') or '').strip()
    brand = str(getattr(legacy, 'DISPLAY_BRAND', 'Metra Consultation'))
    if data.get('language') == 'en':
        greeting = f'Hello {name},' if name else 'Hello,'
        subject = f'{folder} — Thank you for your trust'
        body = (f'{greeting}\n\nThank you for trusting {brand} with your project. '
                'Now that our work is complete, we would appreciate it if you could '
                'take a moment to share your experience on Google:\n\n'
                f'{review_url()}\n\nYour feedback means a lot to our team. Thank you for your time!'
                f'\n\nBest regards,\nArash Rohani\n{brand}')
    else:
        greeting = f'Bonjour {name},' if name else 'Bonjour,'
        subject = f'{folder} — Merci de votre confiance'
        body = (f'{greeting}\n\nMerci d’avoir fait confiance à {brand} pour votre projet. '
                'Maintenant que notre mandat est terminé, nous vous invitons à prendre '
                'un moment pour partager votre expérience sur Google :\n\n'
                f'{review_url()}\n\nVotre avis compte beaucoup pour notre équipe. Merci pour votre temps !'
                f'\n\nCordialement,\nArash Rohani\n{brand}')
    return subject, body


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
              '(année en cours). Le message sera préparé pour copie, sans envoi automatique.', rows)


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
        legacy.tg(chat_id, f'⭐ Message prêt à copier\nProjet : {folder}\nCourriel : {email}\nObjet : {subject}')
        legacy.tg(chat_id, body, [[{'text': '🌐 Ouvrir le lien Google', 'url': review_url()}]])
    except Exception:
        legacy.logger.exception('Google review preparation failed')
        legacy.tg(chat_id, '❌ Impossible de préparer le message. Réessayez plus tard.')


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
