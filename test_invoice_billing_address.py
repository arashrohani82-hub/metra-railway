"""Billing address confirmation through the deployed webhook and generated PDF."""
import os
import tempfile
from unittest.mock import patch
import io

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='metra-address-test-'))

import app
import runtime
import invoice_control_runtime as control
from invoice_engine import generate_invoice_pdf
from pypdf import PdfReader

USER = 987655555


def dispatch(text=None, callback=None):
    if callback:
        runtime.department_dispatch({'callback_query': {'id': 'address-test', 'data': callback,
            'from': {'id': USER}, 'message': {'chat': {'id': USER}}}})
    else:
        runtime.department_dispatch({'message': {'text': text, 'from': {'id': USER}, 'chat': {'id': USER}}})


def setup_data():
    data = {'name': 'Client', 'addr': '100 Project Street', 'phone': '514-555-1234',
            'email': 'client@example.com', 'project_folder': 'P26-031-AGR',
            'project_created': True, 'price': 1800}
    app.user_data[str(USER)] = data
    return data


def test_edit_requires_confirmation_and_preserves_project_address():
    data = setup_data()
    with patch.object(app, 'ALLOWED_USERS', {USER}), patch.object(app, 'tg'), \
         patch.object(app, 'save_user_data'), patch.object(app.req, 'post'), \
         patch.object(control, '_invoice_status', return_value={'contract': 1800, 'billed': 0, 'remaining': 1800}), \
         patch.object(control.preview, 'show_invoice_preview_pdf') as preview:
        control.show_invoice_preview_control(USER, str(USER), percentage=25)
        assert data['project_address'] == '100 Project Street'
        preview.assert_not_called()
        dispatch(callback='invoice_address_edit')
        dispatch(text='200 Billing Avenue\nMontreal QC H1H 1H1')
        assert data['addr'].startswith('200 Billing Avenue')
        assert data['project_address'] == '100 Project Street'
        preview.assert_not_called()
        dispatch(callback='invoice_address_ok')
        preview.assert_called_once_with(USER, str(USER), percentage=25, fixed_amount=None)
        assert control._billing_address_is_confirmed(data)


def test_default_address_can_be_confirmed_without_editing():
    data = setup_data()
    data['billing_address_preview'] = {'percentage': None, 'fixed_amount': 400}
    with patch.object(app, 'ALLOWED_USERS', {USER}), patch.object(app, 'tg'), \
         patch.object(app, 'save_user_data'), patch.object(app.req, 'post'), \
         patch.object(control, 'show_invoice_preview_control') as preview:
        control.show_billing_address(USER, str(USER))
        dispatch(callback='invoice_address_ok')
        assert data['addr'] == '100 Project Street'
        assert control._billing_address_is_confirmed(data)
        preview.assert_called_once_with(USER, str(USER), percentage=None, fixed_amount=400)


def test_old_send_button_cannot_issue_before_address_confirmation():
    setup_data()['pending_invoice'] = {'percentage': 25}
    with patch.object(app, 'tg'), patch.object(control, '_original_issue_invoice') as issue:
        control.issue_invoice_with_confirmed_address(USER, str(USER))
        issue.assert_not_called()


def test_cancel_exits_edit_without_consuming_next_message():
    data = setup_data()
    data['waiting_billing_address_input'] = True
    data['billing_address_preview'] = {'percentage': 25, 'fixed_amount': None}
    with patch.object(app, 'ALLOWED_USERS', {USER}), patch.object(app, 'save_user_data'):
        assert not control.handle_billing_address({'message': {'from': {'id': USER}, 'text': '❌ Annuler'}})
    assert not data.get('waiting_billing_address_input')
    assert not data.get('billing_address_preview')


def test_pdf_separates_billing_and_project_addresses():
    data = setup_data()
    data.update(addr='200 Billing Avenue', project_address='100 Project Street')
    pdf, _, _ = generate_invoice_pdf(data, 57, percentage=25, logo_path=None)
    text = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    assert '200 Billing Avenue' in text
    assert '100 Project Street' in text
    assert text.index('200 Billing Avenue') < text.index('100 Project Street')
