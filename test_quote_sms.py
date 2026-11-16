import ast
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import quote_sms


class QuoteSmsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            'TWILIO_SMS_ENABLED': 'true',
            'TWILIO_ACCOUNT_SID': 'AC' + 'a' * 32,
            'TWILIO_AUTH_TOKEN': 'test-only-secret',
            'TWILIO_FROM_NUMBER': '+14388129037',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.data = {'phone': '(514) 555-1234', 'odsNum': 'ODS26-135-STR-EDI-Test'}
        self.response = Mock(status_code=201)
        self.response.json.return_value = {'sid': 'SM' + 'b' * 32, 'status': 'queued'}
        self.http = patch.object(quote_sms.requests, 'post', return_value=self.response)
        self.post = self.http.start()
        self.addCleanup(self.http.stop)

    def send(self, data=None):
        return quote_sms.notify_quote(data or self.data, self.tmp.name)

    def test_disabled_or_unconfigured_makes_no_network_call(self):
        with patch.dict(os.environ, {'TWILIO_SMS_ENABLED': 'false'}):
            self.assertEqual(self.send()['status'], 'disabled')
        with patch.dict(os.environ, {'TWILIO_AUTH_TOKEN': ''}):
            self.assertEqual(self.send()['status'], 'not_configured')
        self.post.assert_not_called()

    def test_invalid_and_missing_phone_do_not_send(self):
        for phone in ('', '555-1234', '+33123456789', '5145551234 ext 9', '+15145551234 or +15145551235'):
            self.assertEqual(self.send(dict(self.data, phone=phone))['status'], 'missing_phone')
        self.post.assert_not_called()

    def test_request_and_one_segment_body(self):
        self.assertEqual(self.send()['status'], 'queued')
        kwargs = self.post.call_args.kwargs
        self.assertEqual(kwargs['data']['To'], '+15145551234')
        self.assertEqual(kwargs['data']['From'], '+14388129037')
        self.assertIn('ODS26-135-STR-EDI', kwargs['data']['Body'])
        self.assertLessEqual(len(kwargs['data']['Body']), 160)
        self.assertTrue(kwargs['data']['Body'].isascii())
        self.assertEqual(kwargs['timeout'], (5, 15))

    def test_duplicate_is_durable_and_full_reference_is_used(self):
        self.send()
        self.assertEqual(self.send()['status'], 'duplicate')
        # Another department with the same numeric prefix is a different offer.
        self.assertEqual(self.send(dict(self.data, odsNum='ODS26-135-CIV-EDI'))['status'], 'queued')
        self.assertEqual(self.post.call_count, 2)

    def test_timeout_is_not_retried_and_does_not_expose_secret(self):
        self.post.side_effect = requests.Timeout('secret should not be reported')
        outcome = self.send()
        self.assertEqual(outcome, {'status': 'unknown'})
        self.assertEqual(self.send()['status'], 'duplicate')
        self.assertEqual(self.post.call_count, 1)

    def test_rejection_and_malformed_response_are_not_success(self):
        self.response.status_code = 400
        self.response.json.return_value = {'code': 21610, 'message': 'opted out'}
        self.assertEqual(self.send(), {'status': 'failed', 'code': '21610'})
        self.assertNotIn('transmise', quote_sms.operator_message({'status': 'failed'}))
        self.response.json.side_effect = ValueError()
        self.assertEqual(self.send(dict(self.data, odsNum='ODS26-136-STR-EDI')), {'status': 'unknown'})

    def test_english_body_is_short(self):
        self.send(dict(self.data, language='en'))
        body = self.post.call_args.kwargs['data']['Body']
        self.assertIn('your quote', body)
        self.assertLessEqual(len(body), 160)

    def test_concurrent_sends_reserve_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            outcomes = list(executor.map(lambda _: self.send(), range(8)))
        self.assertEqual(sum(item['status'] == 'queued' for item in outcomes), 1)
        self.post.assert_called_once()


class EmailIntegrationTests(unittest.TestCase):
    """Exercise the actual email function without importing live app services."""
    def setUp(self):
        tree = ast.parse(Path('app.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'send_ods_email')
        import base64
        import urllib.parse
        self.sms = Mock(return_value={'status': 'queued'})
        self.archive = Mock(return_value=['quote.pdf'])
        self.response = Mock(status_code=202, text='test response')
        self.ns = {
            'build_email_preview': lambda data: ('internal@example.com', 'Quote', 'Body'),
            'generate_pdf': lambda data: io.BytesIO(b'pdf'),
            'email_body_html': str, 'microsoft_email_config': lambda: {'EMAIL_SENDER': 'sender@example.com'},
            'graph_access_token': lambda: 'test-only-graph', 'urllib': urllib,
            'base64': base64, 'req': Mock(), 'logger': Mock(),
            'notify_quote': self.sms, 'DATA_DIR': '/unused-test',
            'archive_ods_files': self.archive,
        }
        self.ns['req'].post.return_value = self.response
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py', 'exec'), self.ns)

    def test_failed_email_never_sends_sms(self):
        self.response.status_code = 403
        with self.assertRaises(RuntimeError):
            self.ns['send_ods_email']({})
        self.sms.assert_not_called()
        self.archive.assert_not_called()

    def test_sms_runs_before_archive_and_archive_failure_does_not_cancel_it(self):
        events = []
        self.sms.side_effect = lambda *args: events.append('sms') or {'status': 'queued'}
        def archive(*args):
            events.append('archive')
            raise RuntimeError('archive unavailable')
        self.archive.side_effect = archive
        data = {}
        result = self.ns['send_ods_email'](data)
        self.assertEqual(events, ['sms', 'archive'])
        self.assertEqual(data['sms_notification']['status'], 'queued')
        self.assertEqual(result[0], 'internal@example.com')

    def test_sms_failure_never_changes_successful_email_to_failure(self):
        self.sms.side_effect = OSError('disk unavailable')
        data = {}
        result = self.ns['send_ods_email'](data)
        self.assertEqual(result[0], 'internal@example.com')
        self.assertEqual(data['sms_notification'], {'status': 'unknown'})
        self.archive.assert_called_once()


if __name__ == '__main__':
    unittest.main()
