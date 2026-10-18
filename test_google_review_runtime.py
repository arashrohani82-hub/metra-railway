import os
import tempfile
from unittest.mock import patch
from unittest.mock import Mock

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='review-test-'))
import google_review_runtime as review


def test_unauthorized_callback_cannot_read_projects():
    with patch.object(review.legacy, 'ALLOWED_USERS', set()), patch.object(review.legacy, 'tg'), patch.object(review, 'prepare') as prepare:
        assert review.handle({'callback_query': {'data': 'google_review:abc:pick:0', 'from': {'id': 123}, 'message': {'chat': {'id': 123}}}})
        prepare.assert_not_called()


def test_expired_callback_cannot_select_new_project():
    with patch.object(review.legacy, 'ALLOWED_USERS', {123}), patch.object(review.legacy, 'user_data', {'123': {'google_review_choices': {'token': 'new', 'folders': ['P26-001']}}}), patch.object(review.legacy, 'tg'), patch.object(review.legacy.req, 'post'), patch.object(review, 'prepare') as prepare:
        review.handle({'callback_query': {'data': 'google_review:old:pick:0', 'from': {'id': 123}, 'message': {'chat': {'id': 123}}}})
        prepare.assert_not_called()


def test_prepare_uses_project_client_and_does_not_modify_invoice_session():
    session = {'price': 1200, 'google_review_choices': {'token': 'test', 'folders': ['P26-001-ABC']}}
    with patch.object(review.legacy, 'user_data', {'123': session}), patch.object(review.ods_runtime, '_find_history_by_project_folder', return_value=('ODS', {'data': {'name': 'Client', 'email': 'client@example.com', 'language': 'en'}})), patch.object(review.legacy, 'tg') as tg, patch.object(review.legacy.req, 'post') as post:
        review.prepare(123, '123', 0)
        assert 'client@example.com' in tg.call_args_list[0].args[1]
        assert 'Hello Client,' in tg.call_args_list[1].args[1]
        assert review.DEFAULT_REVIEW_URL in tg.call_args_list[1].args[1]
        assert session['price'] == 1200
        post.assert_not_called()


def test_pagination_reaches_older_projects():
    with patch.object(review.legacy, 'user_data', {'123': {'google_review_choices': {'token': 'abc', 'folders': [f'P26-{i:03}' for i in range(31)]}}}), patch.object(review.legacy, 'tg') as tg:
        review.show_page(123, '123', 2)
        assert tg.call_args.args[2][0][0]['text'] == 'P26-030'


def test_unrelated_updates_fall_through():
    assert review.handle({'message': {'text': '🧾 Facturation'}}) is False


def test_send_requires_current_preview_nonce():
    with patch.object(review.legacy, 'user_data', {}), patch.object(review.legacy, 'tg'), patch.object(review.legacy.req, 'post') as post:
        review.send_request(123, '123', 'expired')
        post.assert_not_called()


def test_confirmed_send_uses_preview_and_prevents_duplicate_after_restart(tmp_path):
    pending = {'nonce': 'confirmed', 'folder': 'P26-001', 'recipient': 'client@example.com', 'subject': 'Preview subject', 'body': 'Preview body'}
    with patch.object(review.legacy, 'DATA_DIR', str(tmp_path)), patch.object(review.legacy, 'user_data', {'123': {'google_review_pending': pending}}), patch.object(review.legacy, 'tg'), patch.object(review.legacy, 'save_user_data'), patch.object(review.legacy, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'info@example.com'}), patch.object(review.legacy, 'graph_access_token', return_value='test'), patch.object(review.legacy.req, 'post', return_value=Mock(status_code=202)) as post:
        review.send_request(123, '123', 'confirmed')
        message = post.call_args.kwargs['json']['message']
        assert message['toRecipients'][0]['emailAddress']['address'] == pending['recipient']
        assert 'Preview body' in message['body']['content']
        assert message['body']['contentType'] == 'HTML'
        assert 'google_review_pending' not in review.legacy.user_data['123']
        review.legacy.user_data['123']['google_review_pending'] = pending
        review.send_request(123, '123', 'confirmed')
        assert post.call_count == 1


def test_uncertain_send_is_not_retried(tmp_path):
    pending = {'nonce': 'confirmed', 'folder': 'P26-002', 'recipient': 'client@example.com', 'subject': 'Subject', 'body': 'Body'}
    with patch.object(review.legacy, 'DATA_DIR', str(tmp_path)), patch.object(review.legacy, 'user_data', {'123': {'google_review_pending': pending}}), patch.object(review.legacy, 'tg'), patch.object(review.legacy, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'info@example.com'}), patch.object(review.legacy, 'graph_access_token', return_value='test'), patch.object(review.legacy.req, 'post', side_effect=TimeoutError) as post:
        review.send_request(123, '123', 'confirmed')
        review.send_request(123, '123', 'confirmed')
        assert post.call_count == 1


def test_cancel_never_sends():
    pending = {'nonce': 'abc'}
    with patch.object(review.legacy, 'ALLOWED_USERS', {123}), patch.object(review.legacy, 'user_data', {'123': {'google_review_pending': pending}}), patch.object(review.legacy, 'save_user_data'), patch.object(review.legacy, 'tg'), patch.object(review.legacy.req, 'post'), patch.object(review, 'send_request') as send:
        review.handle({'callback_query': {'id': 'cancel', 'data': 'google_review:abc:cancel:0', 'from': {'id': 123}, 'message': {'chat': {'id': 123}}}})
        send.assert_not_called()
        assert 'google_review_pending' not in review.legacy.user_data['123']


def test_review_uses_first_name_and_regular_logo_signature_in_both_languages():
    import runtime
    for language, greeting in [('fr', 'Bonjour Marc,'), ('en', 'Hello Marc,')]:
        _, body = review.build_request({'name': 'M. Marc Guay', 'language': language}, 'P26-001')
        assert body.startswith(greeting)
        assert 'Bonjour Marc Guay,' not in body
        markup = review.request_email_html(body)
        assert markup.count('Arash Rohani, ing., P.Eng.') == 1
        assert '/assets/metra-logo.png' in markup
        assert 'mailto:a.rohani@metraconsultation.ca' in markup
        assert 'tel:+14388674131' in markup
        assert f'href="{review.DEFAULT_REVIEW_URL}"' in markup


def test_outgoing_logo_is_embedded_not_remote():
    import runtime
    import base64
    subject, body = review.build_request({'name': 'Marc Guay'}, 'P26-001')
    message = review.build_review_email_message({'subject': subject, 'body': body}, 'client@example.com')
    attachment = message['attachments'][0]
    assert attachment['isInline'] is True
    assert attachment['contentType'] == 'image/png'
    assert f'src="cid:{attachment["contentId"]}"' in message['body']['content']
    assert '/assets/metra-logo.png' not in message['body']['content']
    with open(review.legacy.LOGOS['metra'], 'rb') as logo:
        assert base64.b64decode(attachment['contentBytes']) == logo.read()
    assert message['body']['content'].count('Arash Rohani, ing., P.Eng.') == 1

