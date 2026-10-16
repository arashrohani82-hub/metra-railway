"""Exercise billing handlers without starting the application or external services."""
import ast
import io
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


def load_function(filename, name, namespace):
    tree = ast.parse(Path(__file__).with_name(filename).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
    return namespace[name]


class InvoicePhoneTests(unittest.TestCase):
    def setUp(self):
        self.data = dict(name='Client', addr='100 Rue Exemple', email='client@example.com',
                         project_folder='P26-031-AGR', price=1800)
        self.values = dict(contract=1800, subtotal=450, gst=22.5, qst=44.89, total=517.39)
        self.legacy = Mock()
        self.legacy.user_data = {'1': self.data}
        self.legacy.valid_client_email.side_effect = lambda value: value == 'client@example.com'
        self.legacy.invoice_values.return_value = self.values
        self.legacy.generate_invoice_pdf.return_value = (b'%PDF-preview', self.values, None)
        self.legacy.invoice_filename.return_value = 'invoice.pdf'
        self.legacy.LOGOS = {'metra': None}
        self.preview = load_function('invoice_preview_runtime.py', 'show_invoice_preview_pdf',
            dict(legacy=self.legacy, io=io, logger=logging.getLogger(__name__),
                 next_invoice_number_financial=lambda: 57))

    def test_preview_without_phone_succeeds(self):
        self.assertTrue(self.preview(1, '1', percentage=25))
        self.legacy.tg_doc.assert_called_once()
        self.assertEqual(self.data['pending_invoice']['percentage'], 25)

    def test_missing_required_details_blocks_preview(self):
        del self.data['email']
        self.assertFalse(self.preview(1, '1', percentage=25))
        self.legacy.tg_doc.assert_not_called()

    def test_pdf_failure_returns_false(self):
        self.legacy.generate_invoice_pdf.side_effect = RuntimeError('PDF unavailable')
        with self.assertLogs(level='ERROR'):
            self.assertFalse(self.preview(1, '1', percentage=25))

    def test_cumulative_message_requires_successful_preview(self):
        pdf_preview = Mock()
        handler = load_function('invoice_control_runtime.py', 'show_invoice_preview_control',
            dict(legacy=self.legacy, logger=logging.getLogger(__name__),
                 preview=SimpleNamespace(show_invoice_preview_pdf=pdf_preview),
                 _invoice_status=lambda data: dict(contract=1800, billed=0, remaining=1800),
                 _billing_address_is_confirmed=lambda data: True))
        for succeeded in (False, True):
            with self.subTest(succeeded=succeeded):
                self.legacy.tg.reset_mock()
                pdf_preview.return_value = succeeded
                handler(1, '1', percentage=25)
                self.assertEqual(self.legacy.tg.call_count, int(succeeded))

    def test_client_collection_does_not_require_phone(self):
        tree = ast.parse(Path(__file__).with_name('ods_runtime.py').read_text())
        fields = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'INVOICE_CLIENT_FIELDS' for t in n.targets))
        missing = load_function('ods_runtime.py', '_missing_invoice_client_field',
                                dict(INVOICE_CLIENT_FIELDS=fields, legacy=self.legacy))
        self.assertEqual(missing(self.data), (None, None))

    def test_issuance_without_phone_reaches_generation(self):
        lock = Mock()
        lock.acquire.return_value = True
        generate = Mock(side_effect=RuntimeError('stop before uploads and email'))
        issue = load_function('app.py', 'do_issue_invoice', dict(
            user_data=self.legacy.user_data, invoice_creation_lock=lock,
            tg=self.legacy.tg, valid_client_email=self.legacy.valid_client_email,
            logger=logging.getLogger(__name__), graph_access_token=lambda: 'test-token',
            list_onedrive_children=lambda *args: [], INVOICE_DRIVE_OWNER='test',
            INVOICE_FOLDER='test', next_invoice_number=lambda items: 57,
            generate_invoice_pdf=generate, LOGOS={'metra': None}))
        self.data['pending_invoice'] = dict(percentage=25)
        with self.assertLogs(level='ERROR'):
            issue(1, '1')
        generate.assert_called_once()
        lock.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
