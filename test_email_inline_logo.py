"""Verify the actual branded HTML and Graph send payload agree on the CID."""
import ast
import base64
import html
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from email_inline_logo import LOGO_SOURCE, LOGO_CONTENT_ID, inline_logo_attachment
from test_quote_sms import EmailIntegrationTests


def render_signature(body):
    tree = ast.parse(Path('email_branding_patch.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'email_body_html')
    scope = {'html': html, 'LOGO_URL': LOGO_SOURCE}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'email_branding_patch.py', 'exec'), scope)
    return scope['email_body_html'](body)


def final_runtime_signature():
    """Execute both real branding installers in production order, with no I/O."""
    fake_app = types.ModuleType('app')
    fake_app.app = types.SimpleNamespace(view_functions={}, add_url_rule=lambda *a, **k: None)
    fake_app.LOGOS = {'metra': 'logo_metra.png'}
    fake_app.logger = logging.getLogger('email-signature-test')
    branding = types.ModuleType('email_branding_patch')
    final = types.ModuleType('final_email_branding')
    with patch.dict(sys.modules, {'app': fake_app, 'email_branding_patch': branding,
                                 'final_email_branding': final}):
        exec(compile(Path('email_branding_patch.py').read_text(), 'email_branding_patch.py', 'exec'), branding.__dict__)
        # Simulate an intervening layer restoring an outdated signature.
        fake_app.email_body_html = lambda body: '<img src="https://old.invalid/logo.png">'
        exec(compile(Path('final_email_branding.py').read_text(), 'final_email_branding.py', 'exec'), final.__dict__)
        assert fake_app.email_body_html is branding.email_body_html
        return fake_app.email_body_html


class SignatureTests(unittest.TestCase):
    def test_signature_uses_local_image_and_preserves_contact_details(self):
        markup = render_signature('Bonjour <client>\n\nVoici votre offre.\n\nCordialement,\nOld text')
        self.assertIn('Bonjour &lt;client&gt;', markup)
        self.assertIn(f'src="{LOGO_SOURCE}"', markup)
        self.assertNotIn('/assets/metra-logo.png', markup)
        self.assertIn('Metra Consultation Inc.', markup)
        self.assertIn('a.rohani@metraconsultation.ca', markup)

    def test_attachment_is_real_png_with_matching_inline_content_id(self):
        attachment = inline_logo_attachment('logo_metra.png')
        self.assertTrue(attachment['isInline'])
        self.assertEqual(attachment['contentId'], LOGO_CONTENT_ID)
        self.assertEqual(attachment['contentType'], 'image/png')
        self.assertTrue(base64.b64decode(attachment['contentBytes']).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_send_payload_contains_pdf_and_embedded_signature(self):
        case = EmailIntegrationTests()
        case.setUp()
        case.ns['email_body_html'] = final_runtime_signature()
        case.ns['send_ods_email']({'odsNum': 'ODS26-159-STR-HSU', 'name': 'Internal test'})
        message = case.ns['req'].post.call_args.kwargs['json']['message']
        self.assertIn(f'src="cid:{LOGO_CONTENT_ID}"', message['body']['content'])
        attachments = message['attachments']
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]['contentType'], 'application/pdf')
        self.assertEqual(attachments[1]['contentId'], LOGO_CONTENT_ID)
        self.assertTrue(attachments[1]['isInline'])
        case.sms.assert_called_once()

    def test_final_runtime_layer_keeps_shared_cid_signature(self):
        rendered = final_runtime_signature()('Bonjour Arash,\n\nTest.\n\nCordialement,')
        self.assertIn(f'src="{LOGO_SOURCE}"', rendered)
        self.assertNotIn('/assets/metra-logo.png', rendered)
        imports = [node.names[0].name for node in ast.parse(Path('runtime.py').read_text()).body
                   if isinstance(node, ast.Import)]
        self.assertLess(imports.index('email_branding_patch'), imports.index('final_email_branding'))


if __name__ == '__main__':
    unittest.main()
