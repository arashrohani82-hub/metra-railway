import os
import tempfile
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='metra-capacity-test-'))

import app
import project_capacity_runtime as capacity
import runtime
import ods_runtime
from test_project_receivables import register


def test_latest_receipts_and_manual_closures_feed_the_same_report():
    import payment_receipt_runtime as receipts
    folders = [{'name': 'P26-032-VDB'}, {'name': 'P26-007-ABC'}, {'name': 'P26-035-ICK'}]
    with patch.object(app, 'microsoft_email_config', return_value={'EMAIL_SENDER': 'owner'}), \
         patch.object(app, 'graph_access_token', return_value='test'), \
         patch.object(app, 'download_onedrive_path', return_value=register([
             ('P26-032', None, 0, None), ('P26-007', 'Cancelled', 0, None),
             ('P26-035', None, 1, 'Paid')],
             {'P26-032': 1800, 'P26-007': 6000, 'P26-035': 6500})), \
         patch.object(receipts, 'project_received_fractions', return_value={'P26-032': .25}):
        rows = ods_runtime.projects_awaiting_settlement(folders, include_financials=True)
    report = capacity.capacity(rows)
    assert len(report['projects']) == 1
    assert report['total'] == Decimal('1350.00')
    assert report['tax_included'] == Decimal('1552.16')


def test_unknowns_do_not_become_zero_and_remaining_values_are_ranked():
    report = capacity.capacity([
        {'name': 'P26-023-4HE', 'contract': 1500, 'received_fraction': .6231064724215409},
        {'name': 'P26-039-APL', 'contract': 4500, 'received_fraction': .25},
        {'name': 'P26-040-GNX', 'contract': 1800, 'received_fraction': None},
        {'name': 'P26-041-UWC', 'contract': None, 'received_fraction': 0},
        {'name': 'P26-039-duplicate', 'contract': 4500, 'received_fraction': .25},
    ])
    assert report['total'] == Decimal('3940.34')
    assert len(report['unknown']) == 2
    assert [p['code'] for p in report['projects']] == ['P26-039', 'P26-023']
    assert report['projects'][1]['tax_included'] == Decimal('650.00')
    assert 'hors total' in capacity.summary_text(report)


def test_capacity_button_bypasses_active_invoice_text_input():
    user = 987654329
    app.user_data[str(user)] = {'waiting_billing_address_input': True}
    with patch.object(app, 'ALLOWED_USERS', {user}), patch.object(app, 'tg'), \
         patch.object(app.executor, 'submit') as submit:
        runtime.department_dispatch({'message': {'from': {'id': user}, 'chat': {'id': user},
                                               'text': capacity.BUTTON}})
        submit.assert_called_once_with(capacity.show, user, str(user), 0)
    assert not any(c.get('text') == capacity.BUTTON for row in app.main_menu()['keyboard'] for c in row)


def test_private_financials_require_authorized_actor():
    with patch.object(app, 'ALLOWED_USERS', {1}), patch.object(app, 'tg') as tg, \
         patch.object(app.executor, 'submit') as submit:
        assert capacity.handle({'callback_query': {'from': {'id': 2}, 'id': 'test',
            'message': {'chat': {'id': 2}}, 'data': capacity.PREFIX + 'page:0'}})
    submit.assert_not_called()
    assert 'privé' in tg.call_args.args[1]


def test_report_failure_is_not_an_empty_balance():
    with patch.object(capacity, 'load_capacity', side_effect=RuntimeError('unavailable')), \
         patch.object(app, 'tg') as tg:
        capacity.show(1, '1')
    assert 'Impossible' in tg.call_args.args[1]
    assert '0,00' not in tg.call_args.args[1]
