"""Marketing drafts stay private, durable and independent of proposal intake."""
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='marketing-test-'))
import app
import runtime
import marketing_runtime as marketing


def message(text, uid=123):
    return {'message': {'from': {'id': uid}, 'chat': {'id': uid}, 'text': text}}


def callback(data, uid=123):
    return {'callback_query': {'id': 'click', 'from': {'id': uid},
                               'message': {'chat': {'id': uid}}, 'data': 'mkt:' + data}}


def test_bilingual_template_and_custom_email_survive_sessions(tmp_path):
    with patch.object(app, 'DATA_DIR', str(tmp_path)), patch.object(app, 'ALLOWED_USERS', {123}), \
         patch.object(app, 'tg') as tg, patch.object(app.req, 'post') as post:
        runtime.department_dispatch(message(marketing.BUTTON))
        assert 'Choose a language' in tg.call_args.args[1]
        marketing.handle(callback('lang:en'))
        marketing.handle(callback('template:coop'))
        assert 'Hello,' in tg.call_args.args[1]
        marketing.handle(callback('add'))
        for text in ('Architects', 'Working together', 'Hello,\n\nMy exact custom text.'):
            assert marketing.handle(message(text))
        with marketing.database() as db:
            row = db.execute('SELECT * FROM drafts').fetchone()
            draft_id = row['id']
            assert row['lang'] == 'en'
            assert row['body'] == 'Hello,\n\nMy exact custom text.'
        marketing.handle(callback('body:' + str(draft_id)))
        marketing.handle(message('Revised body'))
        marketing.handle(callback('lang:fr'))
        marketing.handle(callback('template:intro'))
        assert tg.call_args.args[1].startswith('Bonjour,')
        marketing.handle(callback('lang:en'))
        marketing.handle(callback('view:' + str(draft_id)))
        assert tg.call_args.args[1] == 'Revised body'
        # Only Telegram callback acknowledgements; never Graph, sendMail or AI.
        assert all(call.args[0].endswith('/answerCallbackQuery') for call in post.call_args_list)


def test_access_controls_and_language_isolation(tmp_path):
    with patch.object(app, 'DATA_DIR', str(tmp_path)), patch.object(app, 'ALLOWED_USERS', {123, 456}), \
         patch.object(app, 'tg') as tg, patch.object(app.req, 'post'):
        marketing.handle(callback('save:intro'))
        with marketing.database() as db:
            draft_id = db.execute('SELECT id FROM drafts').fetchone()['id']
        marketing.handle(callback('view:' + str(draft_id), 456))
        assert 'introuvable' in tg.call_args.args[1]
        marketing.handle(callback('lang:en'))
        marketing.handle(callback('view:' + str(draft_id)))
        assert 'not found' in tg.call_args.args[1]
        marketing.handle(callback('body:' + str(draft_id), 999))
        assert 'privé' in tg.call_args.args[1]


def test_cancel_and_navigation_do_not_capture_ods_text(tmp_path):
    with patch.object(app, 'DATA_DIR', str(tmp_path)), patch.object(app, 'ALLOWED_USERS', {123}), \
         patch.object(app, 'tg'), patch.object(app.req, 'post'):
        marketing.handle(callback('add'))
        assert marketing.handle(message('🧾 Facturation')) is False
        assert marketing.handle(message('Client project address')) is False
        marketing.handle(callback('add'))
        marketing.handle(callback('home'))
        assert marketing.handle(message('Another project')) is False
        with marketing.database() as db:
            assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 0


def test_repeated_template_save_and_pagination(tmp_path):
    with patch.object(app, 'DATA_DIR', str(tmp_path)), patch.object(app, 'ALLOWED_USERS', {123}), \
         patch.object(app, 'tg') as tg, patch.object(app.req, 'post'):
        for _ in range(2):
            marketing.handle(callback('save:intro'))
        with marketing.database() as db:
            assert db.execute('SELECT COUNT(*) FROM drafts').fetchone()[0] == 1
            for i in range(10):
                db.execute('INSERT INTO drafts (uid, lang, title, subject, body) VALUES (?, ?, ?, ?, ?)',
                           ('123', 'fr', 'Draft ' + str(i), 'Subject', 'Body'))
        marketing.handle(callback('list:1'))
        assert len(tg.call_args.args[2]) >= 4


def test_actual_reply_keyboard_replaces_help():
    labels = [cell['text'] for row in app.main_menu()['keyboard'] for cell in row]
    assert marketing.BUTTON in labels
    assert '❓ Aide' not in labels
