"""Bilingual, persistent marketing draft library. No email delivery actions."""
import os
import sqlite3
from contextlib import closing, contextmanager

import app as legacy

BUTTON = '📣 Marketing'
PREFIX = 'mkt:'
PAGE_SIZE = 8
SIGNATURE = ('Arash Rohani, ing., P.Eng.\nMetra Consultation Inc.\n'
             'a.rohani@metraconsultation.ca | (438) 867-4131\nmetraconsultation.ca')
COPY = {
    'fr': {
        'home': '📣 Marketing — Français\n\nChoisissez un modèle ou ajoutez votre propre courriel. Les textes sont enregistrés et prêts à copier.',
        'intro': '🏢 Présentation de Metra', 'coop': '🤝 Demande de collaboration',
        'follow': '📨 Suivi de prise de contact', 'saved': '📂 Mes courriels',
        'add': '➕ Ajouter un courriel', 'edit': '✏️ Modifier le texte',
        'subject_edit': '✏️ Modifier l’objet', 'save': '💾 Enregistrer ce modèle',
        'back': '⬅️ Marketing', 'cancel': '❌ Annuler', 'lang': '🌐 Français / English',
        'title_prompt': 'Quel titre souhaitez-vous donner à ce courriel ?',
        'subject_prompt': 'Indiquez l’objet du courriel.',
        'body_prompt': 'Collez le texte complet du courriel, avec la signature souhaitée.',
        'saved_ok': '✅ Courriel enregistré.', 'empty': 'Aucun courriel enregistré dans cette langue.',
        'missing': 'Ce courriel est introuvable. Ouvrez de nouveau Marketing.',
        'cancelled': 'Modification annulée.', 'subject': 'Objet', 'ready': '📋 Texte prêt à copier',
        'limit': 'Texte trop long. Maximum : {limit} caractères.',
    },
    'en': {
        'home': '📣 Marketing — English\n\nChoose a template or add your own email. Drafts are saved and ready to copy.',
        'intro': '🏢 Introduce Metra', 'coop': '🤝 Request collaboration',
        'follow': '📨 Follow up on an introduction', 'saved': '📂 My emails',
        'add': '➕ Add an email', 'edit': '✏️ Edit text',
        'subject_edit': '✏️ Edit subject', 'save': '💾 Save this template',
        'back': '⬅️ Marketing', 'cancel': '❌ Cancel', 'lang': '🌐 Français / English',
        'title_prompt': 'What title would you like to give this email?',
        'subject_prompt': 'Enter the email subject.',
        'body_prompt': 'Paste the full email text, including your preferred signature.',
        'saved_ok': '✅ Email saved.', 'empty': 'No emails saved in this language yet.',
        'missing': 'Email not found. Open Marketing again.',
        'cancelled': 'Changes cancelled.', 'subject': 'Subject', 'ready': '📋 Ready to copy',
        'limit': 'Text too long. Maximum: {limit} characters.',
    },
}
TEMPLATES = {
    'fr': {
        'intro': ('Présentation de Metra Consultation — Services d’ingénierie',
                  'Bonjour,\n\nJe souhaite vous présenter Metra Consultation, une firme offrant des services en ingénierie de structure, génie civil, géotechnique et inspection de bâtiments.\n\nNous accompagnons les propriétaires, entrepreneurs, architectes et syndicats de copropriété dans leurs projets de rénovation, de construction et d’évaluation de bâtiments.\n\nAvez-vous un projet pour lequel notre équipe pourrait vous accompagner ? Nous serions heureux d’en discuter avec vous.\n\nCordialement,'),
        'coop': ('Possibilité de collaboration avec Metra Consultation',
                 'Bonjour,\n\nJe vous contacte au nom de Metra Consultation afin d’explorer une collaboration avec votre équipe. Nous proposons des services en structure, génie civil, géotechnique et inspection de bâtiments, selon les besoins de chaque mandat.\n\nNous serions heureux d’échanger sur vos projets et sur la façon dont notre expertise pourrait compléter vos services. Seriez-vous disponible pour un bref appel ?\n\nCordialement,'),
        'follow': ('Suivi — Possibilité de collaboration',
                   'Bonjour,\n\nJe me permets de faire un suivi à mon précédent message concernant les services de Metra Consultation et une éventuelle collaboration.\n\nSi vous avez un besoin actuel ou à venir en ingénierie ou en inspection de bâtiments, je serais heureux d’en discuter avec vous.\n\nMerci pour votre temps et au plaisir d’échanger.\n\nCordialement,'),
    },
    'en': {
        'intro': ('Introducing Metra Consultation — Engineering services',
                  'Hello,\n\nI would like to introduce Metra Consultation, a firm offering structural, civil and geotechnical engineering services, as well as building inspections.\n\nWe support property owners, contractors, architects and condominium associations with renovation, construction and building assessment projects.\n\nDo you have a project our team could help with? We would be happy to discuss your needs.\n\nKind regards,'),
        'coop': ('Exploring a collaboration with Metra Consultation',
                 'Hello,\n\nI am reaching out on behalf of Metra Consultation to explore a potential collaboration with your team. We offer structural, civil and geotechnical engineering services and building inspections, tailored to each assignment.\n\nWe would welcome the opportunity to learn about your projects and discuss how our expertise could complement your services. Would you be available for a brief call?\n\nKind regards,'),
        'follow': ('Following up — Potential collaboration',
                   'Hello,\n\nI am following up on my earlier message about Metra Consultation’s services and the possibility of working together.\n\nIf you have any current or upcoming engineering or building inspection needs, I would be happy to discuss them with you.\n\nThank you for your time. I look forward to hearing from you.\n\nKind regards,'),
    },
}


@contextmanager
def database():
    os.makedirs(legacy.DATA_DIR, exist_ok=True)
    # Autocommit makes saves durable before the success message and avoids
    # holding a database write lock while Telegram requests are in flight.
    with closing(sqlite3.connect(os.path.join(legacy.DATA_DIR, 'marketing.sqlite3'),
                                 timeout=15, isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY, uid TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL)')
        db.execute("CREATE TABLE IF NOT EXISTS sessions (uid TEXT PRIMARY KEY, lang TEXT NOT NULL DEFAULT 'fr', step TEXT NOT NULL DEFAULT '', draft_id INTEGER, title TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '')")
        yield db


def session(db, uid):
    db.execute('INSERT OR IGNORE INTO sessions (uid) VALUES (?)', (uid,))
    return dict(db.execute('SELECT * FROM sessions WHERE uid=?', (uid,)).fetchone())


def reset(db, uid):
    db.execute("UPDATE sessions SET step='', draft_id=NULL, title='', subject='' WHERE uid=?", (uid,))


def send(chat, text, rows=None):
    # Marketing language is selected independently of proposal language. Preserve
    # custom text exactly instead of passing it through automatic translation.
    from proposal_language import LANGUAGE
    token = LANGUAGE.set('fr')
    try:
        legacy.tg(chat, text, rows)
    finally:
        LANGUAGE.reset(token)


def button(label, action):
    return {'text': label, 'callback_data': PREFIX + action}


def home(chat, lang):
    c = COPY[lang]
    send(chat, c['home'], [
        [button('📸 Nouveau contact / New contact', 'contact')],
        [button(c[k], 'template:' + k) for k in ('intro', 'coop')],
        [button(c['follow'], 'template:follow')],
        [button(c['saved'], 'list:0'), button(c['add'], 'add')],
        [button(c['lang'], 'languages')],
    ])


def show_draft(db, chat, uid, lang, key):
    c = COPY[lang]
    if key in TEMPLATES[lang]:
        subject, body = TEMPLATES[lang][key]
        body += '\n\n' + SIGNATURE
        actions = [[button(c['save'], 'save:' + key)]]
    else:
        row = db.execute('SELECT * FROM drafts WHERE id=? AND uid=? AND lang=?', (key, uid, lang)).fetchone()
        if not row:
            send(chat, c['missing'])
            return
        subject, body = row['subject'], row['body']
        actions = [[button(c['subject_edit'], 'subject:' + str(row['id'])),
                    button(c['edit'], 'body:' + str(row['id']))]]
    send(chat, c['ready'] + '\n' + c['subject'] + ': ' + subject)
    actions.append([button(c['back'], 'home')])
    send(chat, body, actions)


def show_list(db, chat, uid, lang, page):
    c = COPY[lang]
    rows = db.execute('SELECT id, title FROM drafts WHERE uid=? AND lang=? ORDER BY id DESC LIMIT ? OFFSET ?',
                      (uid, lang, PAGE_SIZE + 1, page * PAGE_SIZE)).fetchall()
    buttons = [[button(row['title'][:55], 'view:' + str(row['id']))] for row in rows[:PAGE_SIZE]]
    nav = []
    if page:
        nav.append(button('◀️', 'list:' + str(page - 1)))
    if len(rows) > PAGE_SIZE:
        nav.append(button('▶️', 'list:' + str(page + 1)))
    if nav:
        buttons.append(nav)
    buttons += [[button(c['add'], 'add')], [button(c['back'], 'home')]]
    send(chat, c['saved'] if rows else c['empty'], buttons)


def handle(update):
    cb = update.get('callback_query') or {}
    msg = cb.get('message') or update.get('message') or {}
    text = str(msg.get('text') or '').strip() if not cb else ''
    action = str(cb.get('data') or '')
    actor = cb.get('from') or msg.get('from') or {}
    uid = str(actor.get('id') or '')
    chat = (msg.get('chat') or {}).get('id')
    entry = text in (BUTTON, '/marketing')
    own_callback = action.startswith(PREFIX)
    if actor.get('id') not in legacy.ALLOWED_USERS:
        if entry or own_callback:
            send(chat, '⛔ Ce bot est privé.')
            return True
        return False
    with database() as db:
        state = session(db, uid)
        lang = state['lang']
        c = COPY[lang]
        if not entry and not own_callback:
            if cb or not state['step']:
                return False
            # Main-menu navigation must never become draft text.
            from menu_guard_runtime import MAIN_MENU_COMMANDS
            menu_labels = {cell['text'] for row in legacy.main_menu()['keyboard'] for cell in row}
            from proposal_language import _CACHE
            menu_labels.update(_CACHE.get(label, label) for label in list(menu_labels))
            if text.startswith('/') or text in MAIN_MENU_COMMANDS or text in menu_labels or text in ('❌ Cancel', '📝 New proposal'):
                reset(db, uid)
                return False
            if not text:
                send(chat, c['body_prompt'] if state['step'] in ('body', 'edit_body') else c['subject_prompt'])
                return True
            step = state['step']
            limit = 3500 if step in ('body', 'edit_body') else 160
            if len(text) > limit:
                send(chat, c['limit'].format(limit=limit))
                return True
            cancel = [[button(c['cancel'], 'home')]]
            if step == 'title':
                db.execute("UPDATE sessions SET title=?, step='subject' WHERE uid=?", (text, uid))
                send(chat, c['subject_prompt'], cancel)
            elif step == 'subject':
                db.execute("UPDATE sessions SET subject=?, step='body' WHERE uid=?", (text, uid))
                send(chat, c['body_prompt'], cancel)
            elif step == 'body':
                cursor = db.execute('INSERT INTO drafts (uid, lang, title, subject, body) VALUES (?, ?, ?, ?, ?)',
                                    (uid, lang, state['title'], state['subject'], text))
                reset(db, uid)
                send(chat, c['saved_ok'])
                show_draft(db, chat, uid, lang, cursor.lastrowid)
            elif step in ('edit_body', 'edit_subject'):
                column = 'body' if step == 'edit_body' else 'subject'
                changed = db.execute(f'UPDATE drafts SET {column}=? WHERE id=? AND uid=? AND lang=?',
                                     (text, state['draft_id'], uid, lang)).rowcount
                reset(db, uid)
                send(chat, c['saved_ok'] if changed else c['missing'])
                if changed:
                    show_draft(db, chat, uid, lang, state['draft_id'])
            return True
        reset(db, uid)
        if cb.get('id'):
            try:
                legacy.req.post(f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                                json={'callback_query_id': cb['id']}, timeout=3)
            except Exception:
                pass
        command = action[len(PREFIX):] if own_callback else 'languages'
        if command == 'contact':
            import marketing_contact_runtime
            marketing_contact_runtime.start(chat, uid, lang)
        elif command == 'languages':
            send(chat, '📣 Marketing\n\nChoisissez la langue / Choose a language:',
                 [[button('🇫🇷 Français', 'lang:fr'), button('🇬🇧 English', 'lang:en')]])
        elif command in ('lang:fr', 'lang:en'):
            lang = command.split(':')[1]
            db.execute('UPDATE sessions SET lang=? WHERE uid=?', (lang, uid))
            home(chat, lang)
        elif command == 'home':
            home(chat, lang)
        elif command == 'add':
            db.execute("UPDATE sessions SET step='title' WHERE uid=?", (uid,))
            send(chat, c['title_prompt'], [[button(c['cancel'], 'home')]])
        else:
            verb, _, key = command.partition(':')
            if verb == 'template' and key in TEMPLATES[lang]:
                show_draft(db, chat, uid, lang, key)
            elif verb == 'save' and key in TEMPLATES[lang]:
                subject, body = TEMPLATES[lang][key]
                # Repeated taps on a template's save button reuse the same draft.
                row = db.execute('SELECT id FROM drafts WHERE uid=? AND lang=? AND title=?', (uid, lang, c[key])).fetchone()
                draft_id = row['id'] if row else db.execute('INSERT INTO drafts (uid, lang, title, subject, body) VALUES (?, ?, ?, ?, ?)',
                                                           (uid, lang, c[key], subject, body + '\n\n' + SIGNATURE)).lastrowid
                show_draft(db, chat, uid, lang, draft_id)
            elif verb == 'list' and key.isdigit() and len(key) < 7:
                show_list(db, chat, uid, lang, int(key))
            elif verb == 'view' and key.isdigit():
                show_draft(db, chat, uid, lang, key)
            elif verb in ('subject', 'body') and key.isdigit():
                row = db.execute('SELECT id FROM drafts WHERE id=? AND uid=? AND lang=?', (key, uid, lang)).fetchone()
                if row:
                    db.execute('UPDATE sessions SET step=?, draft_id=? WHERE uid=?', ('edit_' + verb, key, uid))
                    send(chat, c[verb + '_prompt'], [[button(c['cancel'], 'home')]])
                else:
                    send(chat, c['missing'])
            else:
                home(chat, lang)
    return True
