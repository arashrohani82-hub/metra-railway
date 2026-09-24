import ast
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.sax.saxutils import escape
import threading
import zipfile

import pytest

from project_phone import PhoneStore, PhoneStoreError, locate_phone, patch_phone, project_code


def workbook(rows, headers=('Description', 'Email', 'Phone', 'Project Code')):
    def cell(col, row, value):
        if value is None:
            return ''
        if isinstance(value, int):
            return f'<c r="{col}{row}"><v>{value}</v></c>'
        if str(value).startswith('='):
            return f'<c r="{col}{row}"><f>{escape(value[1:])}</f><v>0</v></c>'
        return f'<c r="{col}{row}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    data = [headers, *rows]
    xml = ''.join(f'<row r="{i}">' + ''.join(cell(chr(65+j), i, v) for j, v in enumerate(row)) + '</row>' for i, row in enumerate(data, 1))
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="data 2026" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:D%d"/><sheetData>%s</sheetData></worksheet>' % (len(data), xml),
        'preserved-extension.xml': '<untouched>Native objects and formulas must survive</untouched>',
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return out.getvalue()


def test_lookup_uses_project_code_not_description_or_suffix():
    data = workbook([('P26-031 misleading description', 'a@example.com', 'WRONG', 'P26-032'),
                     ('Different description', 'b@example.com', '+1 514 555 1234', 'P26-031-AGR-original')])
    assert locate_phone(data, 'P26-031-AGR-renamed')[2] == '+1 514 555 1234'
    assert project_code(' p26-031-AGR-New ') == 'P26-031'
    with pytest.raises(PhoneStoreError):
        project_code('P26-0310')


def test_blank_phone_roundtrip_preserves_every_other_zip_part_and_cell():
    data = workbook([('=1+1', 'a@example.com', None, 'P26-031'), ('Other', 'b@example.com', 'UNCHANGED', 'P26-032')])
    phone = '+01 (514) 555-1234 poste 02'
    updated = patch_phone(data, 'P26-031', phone)
    assert locate_phone(updated, 'P26-031')[2] == phone
    assert locate_phone(updated, 'P26-032')[2] == 'UNCHANGED'
    assert patch_phone(updated, 'P26-031', phone) == updated
    with zipfile.ZipFile(io.BytesIO(data)) as old, zipfile.ZipFile(io.BytesIO(updated)) as new:
        assert old.namelist() == new.namelist()
        for name in old.namelist():
            if name != 'xl/worksheets/sheet1.xml':
                assert old.read(name) == new.read(name)
        inserted = f'<c r="C2" t="inlineStr"><is><t>{phone}</t></is></c>'.encode()
        assert new.read('xl/worksheets/sheet1.xml').replace(inserted, b'') == old.read('xl/worksheets/sheet1.xml')


@pytest.mark.parametrize('rows,code', [
    ([('Other', '', None, None)], 'P26-031'),
    ([('A', '', None, 'P26-031'), ('B', '', None, 'P26-031-AGR')], 'P26-031'),
    ([('A', '', '=1+1', 'P26-031')], 'P26-031'),
    ([('A', '', 'Existing', 'P26-031')], 'P26-031'),
])
def test_ambiguous_missing_formula_or_existing_phone_never_overwritten(rows, code):
    with pytest.raises(PhoneStoreError):
        patch_phone(workbook(rows), code, 'New')


def test_numeric_phone_is_not_scientific_notation():
    assert locate_phone(workbook([('A', '', 5145551234, 'P26-031')]), 'P26-031')[2] == '5145551234'


@pytest.mark.parametrize('headers', [('Description','Email','Other','Project Code'), ('Phone','Email','Phone','Project Code')])
def test_missing_or_duplicate_header_fails_without_schema_mutation(headers):
    with pytest.raises(PhoneStoreError):
        patch_phone(workbook([('A', '', None, 'P26-031')], headers), 'P26-031', '5145551234')


def test_store_uses_etag_and_rereads_row_after_it_moves():
    data = workbook([('Other', '', '', 'P26-032'), ('A', '', None, 'P26-031')])
    updated = patch_phone(data, 'P26-031', '+1 514 555 1234')
    legacy = SimpleNamespace(ods_list_lock=threading.Lock(), req=Mock(), graph_access_token=lambda:'token',
                             microsoft_email_config=lambda:{'EMAIL_SENDER':'owner@example.com'}, ODS_LIST_PATH='List.xlsx')
    response = lambda **kw: SimpleNamespace(status_code=200, **kw)
    legacy.req.get.side_effect = [response(json=lambda:{'eTag':'"v1"'}),response(content=data),
                                  response(json=lambda:{'eTag':'"v1"'}),response(content=updated)]
    legacy.req.put.return_value = response()
    PhoneStore(legacy).save('P26-031', '+1 514 555 1234')
    assert legacy.req.put.call_args.kwargs['headers']['If-Match'] == '"v1"'
    assert locate_phone(legacy.req.put.call_args.kwargs['data'], 'P26-031')[1] == 'C3'


def runtime_context(store):
    # Execute the actual handlers without bootstrapping Telegram/Graph or Flask.
    names = {'select_onedrive_project','handle_update_runtime','_missing_invoice_client_field',
             '_ask_missing_invoice_client_field','_continue_invoice_after_client_details'}
    tree = ast.parse(Path('ods_runtime.py').read_text())
    definitions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    legacy = SimpleNamespace(user_data={'1':{'invoice_project_choices':{'1':{'folder':'P26-031-AGR-renamed'}}}},
                             tg=Mock(),save_user_data=Mock(),ALLOWED_USERS={1},valid_client_email=lambda x:x)
    namespace = dict(legacy=legacy,base=SimpleNamespace(show_invoice_options_multi=Mock()),
                     logger=Mock(),project_code=project_code,PhoneStore=lambda _:store,
                     _find_history_by_project_folder=lambda f:(None,None),
                     recover_project_metadata_from_onedrive=lambda f:dict(name='Test',addr='Test',email='test@example.com',phone='STALE ARCHIVE',price=2500),
                     INVOICE_CLIENT_FIELDS=(('name','nom'),('addr','adresse'),('phone','numéro de téléphone'),('email','courriel')),
                     _original_handle_update=Mock())
    exec(compile(definitions, 'ods_runtime.py', 'exec'), namespace)
    return namespace, legacy


def test_runtime_blank_phone_asks_then_persists_before_continuing():
    store = Mock()
    store.read.return_value = ''
    ns, legacy = runtime_context(store)
    ns['select_onedrive_project'](1,'1','1')
    assert legacy.user_data['1']['phone'] == ''
    assert legacy.user_data['1']['waiting_invoice_client_field'] == 'phone'
    ns['handle_update_runtime']({'message':{'from':{'id':1},'chat':{'id':1},'text':'+1 514 555 1234'}})
    store.save.assert_called_once_with('P26-031', '+1 514 555 1234')
    assert 'waiting_invoice_client_field' not in legacy.user_data['1']
    ns['base'].show_invoice_options_multi.assert_called_once_with(1,'1')
    store.read.return_value = '+1 514 555 1234'
    legacy.tg.reset_mock()
    ns['select_onedrive_project'](1,'1','1')
    assert legacy.user_data['1']['phone'] == '+1 514 555 1234'
    legacy.tg.assert_not_called()


def test_runtime_save_failure_does_not_advance_or_claim_persistence():
    store = Mock(); store.read.return_value = ''; store.save.side_effect = PhoneStoreError('HTTP 412')
    ns, legacy = runtime_context(store)
    ns['select_onedrive_project'](1,'1','1')
    ns['handle_update_runtime']({'message':{'from':{'id':1},'chat':{'id':1},'text':'5145551234'}})
    assert legacy.user_data['1']['waiting_invoice_client_field'] == 'phone'
    assert legacy.user_data['1']['phone'] == ''
    ns['base'].show_invoice_options_multi.assert_not_called()


def test_runtime_missing_project_never_falls_back_to_old_metadata():
    store = Mock(); store.read.side_effect = PhoneStoreError('Project Code absent')
    ns, legacy = runtime_context(store)
    ns['select_onedrive_project'](1,'1','1')
    assert 'phone' not in legacy.user_data['1']
    ns['base'].show_invoice_options_multi.assert_not_called()


def test_store_aborts_if_workbook_changed_while_downloading():
    legacy = SimpleNamespace(ods_list_lock=threading.Lock(), req=Mock(), graph_access_token=lambda:'token',
                             microsoft_email_config=lambda:{'EMAIL_SENDER':'owner@example.com'}, ODS_LIST_PATH='List.xlsx')
    legacy.req.get.side_effect = [SimpleNamespace(status_code=200,json=lambda:{'eTag':'v1'}),
                                  SimpleNamespace(status_code=200,content=b'not parsed'),
                                  SimpleNamespace(status_code=200,json=lambda:{'eTag':'v2'})]
    with pytest.raises(PhoneStoreError):
        PhoneStore(legacy).save('P26-031','5145551234')
    legacy.req.put.assert_not_called()
