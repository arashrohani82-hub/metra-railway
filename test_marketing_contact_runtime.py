"""Contact extraction never sends; preview confirmation is bound to exact content."""
import base64
import io
import os
import tempfile
from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest
from PIL import Image

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='marketing-contact-test-'))
import app
import runtime
import marketing_contact_runtime as contact


def message(text='', uid=123, **extra):
    return {'message': {'from': {'id': uid}, 'chat': {'id': uid}, 'text': text, **extra}}


def current(uid='123'):
    with contact.database() as db:
        return contact.load(db, uid)


def callback(command, token=None, uid=123):
    token = token or current(str(uid))['token']
    return {'callback_query': {'id': 'click', 'from': {'id': uid}, 'message': {'chat': {'id': uid}},
                               'data': 'mkc:' + token + ':' + command}}


def client(**overrides):
    return {**dict.fromkeys(contact.FIELDS, ''), 'name': 'Marie Tremblay', 'company': 'ABC Architecture',
            'email': 'marie@example.com', 'phone': '514-555-1234', 'request': 'Building renovation', **overrides}


@pytest.fixture
def env(tmp_path):
    with ExitStack() as stack:
        stack.enter_context(patch.object(app, 'DATA_DIR', str(tmp_path)))
        stack.enter_context(patch.object(app, 'ALLOWED_USERS', {123, 456}))
        stack.enter_context(patch.object(app, 'save_user_data'))
        stack.enter_context(patch.object(app, 'user_data', {'123': {'price': 6000, 'language': 'fr'}}))
        tg = stack.enter_context(patch.object(app, 'tg'))
        post = stack.enter_context(patch.object(app.req, 'post', return_value=Mock(status_code=202)))
        yield tg, post


def source(contacts=None, lang='en'):
    runtime.department_dispatch(message('📣 Marketing'))
    with patch.object(contact, 'extract_contacts', return_value=(contacts or [client()], lang)):
        runtime.department_dispatch(message(photo=[{'file_id': 'photo'}]))


def prepare():
    source()
    runtime.department_dispatch(message('پرزنتیشن بفرستم'))
    return current()


def graph_sends(post):
    return [call for call in post.call_args_list if call.args[0].endswith('/sendMail')]


def test_photo_and_natural_intent_create_personalized_preview_without_send(env):
    tg, post = env
    state = prepare()
    assert state['phase'] == 'preview'
    with contact.database() as db:
        row = dict(db.execute('SELECT * FROM marketing_outbox WHERE nonce=?', (state['preview'],)).fetchone())
    assert row['recipient'] == 'marie@example.com'
    assert row['body'].startswith('Hello Marie Tremblay,')
    assert 'ABC Architecture' in str(tg.call_args_list)
    assert app.user_data['123']['price'] == 6000
    assert graph_sends(post) == []


def test_multiple_candidates_require_selection_and_missing_email_is_requested(env):
    tg, post = env
    source([client(), client(name='Jean', email='')], 'fr')
    assert 'selected' not in current()
    contact.handle(callback('compose:intro'))
    assert 'preview' not in current()
    contact.handle(callback('pick:1'))
    contact.handle(callback('compose:coop'))
    assert current()['phase'] == 'edit_email'
    contact.handle(message('info@metraconsultation.ca'))
    assert current()['phase'] == 'edit_email'
    contact.handle(message('jean@example.org'))
    assert current()['phase'] == 'preview'
    assert graph_sends(post) == []


def test_exact_preview_sent_once_with_logo_and_persistent_claim(env):
    tg, post = env
    state = prepare()
    with contact.database() as db:
        approved = dict(db.execute('SELECT * FROM marketing_outbox WHERE nonce=?', (state['preview'],)).fetchone())
    with patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': approved['sender']}), \
         patch.object(app, 'graph_access_token', return_value='test-token'):
        contact.handle(callback('send:' + state['preview']))
        # Reopen durable state as on a fresh process; the same button cannot resend.
        contact.handle(callback('send:' + state['preview']))
    sends = graph_sends(post)
    assert len(sends) == 1
    sent = sends[0].kwargs['json']['message']
    assert sent['subject'] == approved['subject']
    assert sent['toRecipients'][0]['emailAddress']['address'] == approved['recipient']
    assert sent['body']['content'].count('Arash Rohani, ing., P.Eng.') == 1
    assert 'Hello Marie Tremblay,' in sent['body']['content']
    assert 'Cordialement' not in sent['body']['content']
    assert sent['attachments'][0]['isInline'] is True
    with contact.database() as db:
        assert db.execute('SELECT status FROM marketing_outbox').fetchone()['status'] == 'sent'


def test_edit_and_cancel_invalidate_old_confirmation(env):
    tg, post = env
    state = prepare()
    nonce = state['preview']
    contact.handle(callback('edit:body'))
    contact.handle(message('Hello,\n\nExact revised text.\n\nArash'))
    new_nonce = current()['preview']
    assert new_nonce != nonce
    contact.handle(callback('send:' + nonce))
    contact.handle(callback('cancel'))
    contact.handle(callback('send:' + new_nonce, token=state['token']))
    assert graph_sends(post) == []


def test_timeout_never_retries_a_possible_send(env):
    tg, post = env
    state = prepare()
    def respond(url, **kwargs):
        if url.endswith('/sendMail'):
            raise TimeoutError('Delivery outcome unknown')
        return Mock(status_code=200)
    post.side_effect = respond
    with patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': app.EMAIL_SENDER}), \
         patch.object(app, 'graph_access_token', return_value='test-token'):
        contact.handle(callback('send:' + state['preview']))
        contact.handle(callback('send:' + state['preview']))
    assert len(graph_sends(post)) == 1
    with contact.database() as db:
        assert db.execute('SELECT status FROM marketing_outbox').fetchone()['status'] == 'uncertain'


def test_access_navigation_and_stale_callbacks(env):
    tg, post = env
    state = prepare()
    contact.handle(callback('send:' + state['preview'], token=state['token'], uid=456))
    contact.handle(callback('send:' + state['preview'], token=state['token'], uid=999))
    assert contact.handle(message('🧾 Facturation')) is False
    assert current() is None
    assert contact.handle(message('Client for an offer')) is False
    contact.handle(callback('send:' + state['preview'], token=state['token']))
    assert graph_sends(post) == []


def test_extraction_normalizes_png_and_uses_only_visible_client_data(env):
    buf = io.BytesIO()
    Image.new('RGB', (30, 30), 'white').save(buf, format='PNG')
    model_json = {'language': 'fr', 'contacts': [client(), client(name='Metra', email='a.rohani@metraconsultation.ca')]}
    response = Mock(content=[Mock(text=__import__('json').dumps(model_json))])
    with patch.object(app, '_download_telegram_images', return_value=[base64.b64encode(buf.getvalue()).decode()]), \
         patch.object(app.client.messages, 'create', return_value=response) as model:
        extracted, lang = contact.extract_contacts({'document': {'file_id': 'png', 'mime_type': 'image/png'}})
    assert lang == 'fr'
    assert len(extracted) == 1
    assert extracted[0]['phone'] == '514-555-1234'
    content = model.call_args.kwargs['messages'][0]['content']
    image = content[1]['source']
    assert base64.b64decode(image['data']).startswith(b'\xff\xd8')
    assert 'Do not guess' in str(content)


def test_language_switch_invalidates_preview_and_keeps_contact(env):
    tg, post = env
    state = prepare()
    contact.handle(callback('lang:fr'))
    assert current()['contacts'][0]['name'] == 'Marie Tremblay'
    contact.handle(callback('send:' + state['preview']))
    contact.handle(callback('compose:intro'))
    assert tg.call_args.args[1].startswith('Bonjour Marie Tremblay,')
    assert graph_sends(post) == []


def test_correct_recipient_preserves_edited_body_and_revokes_old_preview(env):
    tg, post = env
    prepare()
    contact.handle(callback('edit:body'))
    contact.handle(message('Custom email with my signature.'))
    old = current()['preview']
    contact.handle(callback('edit:email'))
    contact.handle(message('new.address@example.com'))
    with contact.database() as db:
        row = db.execute('SELECT * FROM marketing_outbox WHERE nonce=?', (current()['preview'],)).fetchone()
        assert row['recipient'] == 'new.address@example.com'
        assert row['body'] == 'Custom email with my signature.'
    contact.handle(callback('send:' + old))
    assert graph_sends(post) == []


def test_configuration_failure_does_not_claim_send(env):
    tg, post = env
    state = prepare()
    with patch.object(app, 'microsoft_email_config', side_effect=RuntimeError('not connected')):
        contact.handle(callback('send:' + state['preview']))
    with contact.database() as db:
        assert db.execute('SELECT status FROM marketing_outbox').fetchone()['status'] == 'ready'
    assert graph_sends(post) == []
