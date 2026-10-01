import io
import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest
from pypdf import PdfReader

os.environ.setdefault('ANTHROPIC_API_KEY','test-key')
os.environ.setdefault('DATA_DIR',tempfile.mkdtemp(prefix='metra-receipt-test-'))

import app
import runtime
import invoice_control_runtime as control
import payment_receipt_runtime as receipts
from payment_receipts import money, parse_amount, invoice_details, payment_balance, validate_payment, receipt_pdf
from invoice_engine import generate_invoice_pdf

USER=987661234


def invoice():
    return {'filename':'FAC26-057_P26-040-GNX.pdf','number':'057','total':'517.39',
            'client':'Gregory Shaw','client_lines':['Gregory Shaw','100 Billing Avenue','client@example.com'],
            'email':'client@example.com'}


def pending():
    return {'key':'123456789012345678901234567890ab','invoice':invoice(),
            'amount':'200.00','method':'Interac','date':'2026-09-30','project_folder':'P26-040-GNX'}


def test_decimal_payments_and_overpayments():
    records=[{'amount':'200.00'},{'amount':'100.00'}]
    assert payment_balance(invoice(),records)==(money('300'),money('217.39'))
    assert validate_payment(invoice(),records,'217.39')==money('217.39')
    for value in ('217.40','0','-1','NaN','Infinity'):
        with pytest.raises(ValueError): validate_payment(invoice(),records,value)
    assert parse_amount('1 234,56 $')==money('1234.56')


def test_actual_invoice_pdf_recovers_invoice_client_and_tax_included_total():
    data={'name':'Gregory Shaw','addr':'100 Billing Avenue','project_folder':'P26-040-GNX',
          'price':1800,'email':'client@example.com','phone':'514-555-1234'}
    pdf,_,_=generate_invoice_pdf(data,57,percentage=25,logo_path=None)
    details=invoice_details(PdfReader(io.BytesIO(pdf)).pages[0].extract_text(),invoice()['filename'])
    assert details['total']=='517.39'
    assert details['client']=='Gregory Shaw'
    assert details['email']=='client@example.com'


def test_partial_and_full_receipt_wording():
    record={**pending(),'id':'REC26-057-123456789012','cumulative':'200.00','remaining':'317.39'}
    pdf=receipt_pdf(record)
    text=PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert 'PAIEMENT PARTIEL' in text and '317.39' in text
    assert 'FACTURE ACQUITTÉE' not in text
    record.update(amount='317.39',cumulative='517.39',remaining='0.00')
    text=PdfReader(io.BytesIO(receipt_pdf(record))).pages[0].extract_text()
    assert 'FACTURE ACQUITTÉE' in text
    assert 'PAIEMENT PARTIEL' not in text


def test_confirm_is_idempotent_after_failed_archive_and_restart(tmp_path):
    p=pending()
    app.user_data[str(USER)]={'payment_pending':p}
    with patch.object(receipts,'LEDGER',str(tmp_path/'ledger.json')), \
         patch.object(app,'save_user_data'),patch.object(app,'tg'),patch.object(app,'tg_doc'), \
         patch.object(app,'graph_access_token',return_value='test'), \
         patch.object(app,'create_onedrive_folder'),patch.object(app,'upload_onedrive_path') as upload:
        upload.side_effect=RuntimeError('Network failed')
        with pytest.raises(RuntimeError): receipts.issue_receipt(USER,str(USER),p['key'])
        assert len(receipts.ledger())==1
        # Re-read the durable journal and retry the same confirmation.
        upload.side_effect=None
        receipts.issue_receipt(USER,str(USER),p['key'])
        receipts.issue_receipt(USER,str(USER),p['key'])
        records=receipts.ledger()
        assert len(records)==1
        assert records[p['key']]['cumulative']=='200.00'
        assert records[p['key']]['archived']
        assert not records[p['key']]['emailed']
        assert not app.user_data[str(USER)].get('payment_pending')


def test_confirmation_revalidates_balance_against_another_payment(tmp_path):
    p=pending()
    p['amount']='517.39'
    app.user_data[str(USER)]={'payment_pending':p}
    with patch.object(receipts,'LEDGER',str(tmp_path/'ledger.json')):
        receipts.save_ledger({'other':{'invoice':invoice(),'amount':'100.00'}})
        with pytest.raises(ValueError): receipts.issue_receipt(USER,str(USER),p['key'])
        assert len(receipts.ledger())==1


def test_receipt_button_available_when_project_fully_invoiced():
    app.user_data[str(USER)]={'project_folder':'P26-040-GNX','project_created':True,'price':1800}
    with patch.object(app,'tg') as tg,patch.object(app,'save_user_data'), \
         patch.object(control,'_invoice_status',return_value={'contract':1800,'billed':1800,'remaining':0,'percent':100}):
        control.show_invoice_options_control(USER,str(USER))
        assert tg.call_args.args[2][0][0]['callback_data']=='pay_start'


def test_receipt_callback_uses_final_webhook_dispatch():
    with patch.object(app,'ALLOWED_USERS',{USER}),patch.object(app.req,'post'), \
         patch.object(receipts,'show_invoices') as show:
        runtime.department_dispatch({'callback_query':{'id':'test','data':'pay_start',
            'from':{'id':USER},'message':{'chat':{'id':USER}}}})
        show.assert_called_once_with(USER,str(USER))


def test_unauthorized_actor_cannot_record_payment():
    with patch.object(app,'ALLOWED_USERS',set()),patch.object(app,'tg'), \
         patch.object(receipts,'issue_receipt') as issue:
        receipts.handle_update({'callback_query':{'id':'test','data':'pay_confirm:abc',
            'from':{'id':USER},'message':{'chat':{'id':USER}}}})
        issue.assert_not_called()


def test_future_date_and_cancellation(tmp_path):
    app.user_data[str(USER)]={'payment_pending':pending(),'payment_waiting':'date'}
    with patch.object(app,'ALLOWED_USERS',{USER}),patch.object(app,'tg'),patch.object(app,'save_user_data'), \
         patch.object(receipts,'today',return_value=date(2026,9,30)):
        receipts.handle_update({'message':{'from':{'id':USER},'chat':{'id':USER},'text':'2026-10-01'}})
        assert app.user_data[str(USER)]['payment_pending']['date']=='2026-09-30'
        assert not receipts.handle_update({'message':{'from':{'id':USER},'chat':{'id':USER},'text':'❌ Annuler'}})
        assert not app.user_data[str(USER)].get('payment_pending')


def test_email_only_after_explicit_button_and_duplicate_send_is_blocked(tmp_path):
    p=pending()
    record={**p,'uid':str(USER),'id':'REC26-057-123456789012','cumulative':'200.00',
            'remaining':'317.39','archived':True,'emailed':False}
    with patch.object(receipts,'LEDGER',str(tmp_path/'ledger.json')),patch.object(app,'tg'), \
         patch.object(app,'graph_access_token',return_value='test'),patch.object(app.req,'post') as send:
        receipts.save_ledger({p['key']:record})
        send.return_value.status_code=202
        receipts.send_receipt(USER,str(USER),p['key'])
        receipts.send_receipt(USER,str(USER),p['key'])
        send.assert_called_once()
        assert send.call_args.kwargs['json']['message']['toRecipients'][0]['emailAddress']['address']=='client@example.com'
