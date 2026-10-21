"""Production routing and real document coverage without external side effects."""
import copy
import io
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='loi16-tests-'))

import openpyxl
from pypdf import PdfReader
import pytest
import app
import runtime
import loi16_runtime as loi
import ods_recovery
import proposal_language as loc

UID = 987650016


def message(text):
    return {'message': {'from': {'id': UID}, 'chat': {'id': UID}, 'text': text}}


def callback(value):
    return {'callback_query': {'id': 'test', 'from': {'id': UID},
                               'message': {'chat': {'id': UID}}, 'data': value}}


def draft(**extra):
    data = dict(proposal_kind='loi16', department='STR', province='QC', language='fr',
                name='Syndicat Exemple', manager_name='Gestion Exemple',
                addr='123 rue Exemple\nMontréal QC', email='sample@example.test',
                phone='514-555-0100', loi16_units=6, loi16_floors=3,
                loi16_counts_confirmed=True, loi16_equipment=['parking'],
                loi16_equipment_confirmed=True, price=2800, delai='10',
                odsNum='ODS26-144-STR-LOI', date='2026-10-20')
    data.update(extra)
    return loi.normalize(data)


@pytest.fixture(autouse=True)
def isolated():
    app.user_data.pop(str(UID), None)
    app.offers_history.pop(str(UID), None)
    loc.PREFERENCES.clear()
    loc.LANGUAGE.set('fr')
    with patch.object(app, 'ALLOWED_USERS', {UID}), patch.object(app, 'tg', return_value=True) as tg, \
         patch.object(app.req, 'post'), patch.object(app, 'save_user_data'), \
         patch.object(app, 'save_offers_history'):
        yield tg
    app.user_data.pop(str(UID), None)
    app.offers_history.pop(str(UID), None)
    loc.PREFERENCES.clear()


def test_structure_has_quebec_loi16_branch_and_keeps_general_path(isolated):
    app.user_data[str(UID)] = {'province': 'QC', 'language': 'fr'}
    runtime.department_dispatch(callback('dept:STR'))
    assert 'loi16:start' in str(isolated.call_args)
    runtime.department_dispatch(callback('loi16:general'))
    assert not loi.is_loi16(app.user_data[str(UID)])
    assert 'courriel du client' in isolated.call_args.args[1]


def test_three_short_intake_questions_no_structural_conditions(isolated):
    app.user_data[str(UID)] = {'department': 'STR', 'province': 'QC', 'language': 'fr'}
    runtime.department_dispatch(callback('loi16:start'))
    # Read address directly after a failed/unavailable source extraction.
    data = app.user_data[str(UID)]
    data['waiting_field'] = 'loi16_address'
    runtime.department_dispatch(message('123 rue Exemple, Montréal QC'))
    assert 'unités et d’étages' in isolated.call_args.args[1]
    runtime.department_dispatch(message('6 unités, 3 étages'))
    assert 'Ascenseur' in isolated.call_args.args[1]
    runtime.department_dispatch(callback('loi16:eq:parking'))
    runtime.department_dispatch(callback('loi16:eq:done'))
    assert 'Honoraires du forfait' in isolated.call_args.args[1]
    data.update(project_num='144', price=2800, price_confirmed=True, delai='10')
    app.ask_next_missing(UID, str(UID))
    assert 'Prêt à générer' in isolated.call_args.args[1]
    assert not any('hypothèse' in str(call) or 'architecte/technologue' in str(call) for call in isolated.call_args_list)


def test_text_and_photo_extract_all_known_facts_skip_questions(isolated):
    info = dict(syndicate_name='Syndicat Exemple', client_name='Manager', phone='',
                email='sample@example.test', address='123 rue Exemple', units=6, floors=3,
                equipment=['parking'])
    response = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(info))])
    for photo in (False, True):
        app.user_data[str(UID)] = draft()
        with patch.object(app.client.messages, 'create', return_value=response), \
             patch.object(app, '_download_telegram_images', return_value=[]):
            loi.extract(UID, str(UID), text='client request' if not photo else None,
                        file_ids=['photo'] if photo else None)
        result = app.user_data[str(UID)]
        assert result['name'] == 'Syndicat Exemple'
        assert result['manager_name'] == 'Manager'
        assert result['loi16_counts_confirmed'] and result['loi16_equipment_confirmed']
        assert result['waiting_price']
        assert 'Honoraires du forfait' in isolated.call_args.args[1]


def test_unknown_facilities_and_counts_are_not_invented(isolated):
    app.user_data[str(UID)] = loi.normalize({'proposal_kind': 'loi16', 'department': 'STR', 'addr': '123 rue Exemple'})
    runtime.department_dispatch(callback('loi16:counts:unknown'))
    runtime.department_dispatch(callback('loi16:eq:unknown'))
    data = app.user_data[str(UID)]
    assert 'loi16_units' not in data and 'loi16_floors' not in data
    assert 'À confirmer' in loi.document_sections(data)[1][1]
    data['waiting_field'] = None
    assert not loi.handle(message('/menu'))


def test_loi16_callback_cannot_be_used_in_ontario_or_by_unauthorized_user():
    app.user_data[str(UID)] = {'department': 'STR', 'province': 'ON'}
    assert not loi.handle(callback('loi16:start'))
    with patch.object(app, 'ALLOWED_USERS', set()):
        assert not loi.handle(callback('dept:STR'))


@pytest.mark.parametrize('language', ['fr', 'en'])
def test_compact_real_pdf_and_excel_and_no_mutation(language):
    data = draft(language=language)
    before = copy.deepcopy(data)
    pdf = PdfReader(app.generate_pdf(data))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    assert ('25-year reserve fund' if language == 'en' else 'fonds de prévoyance sur 25 ans') in text
    assert '2,800.00' in text
    assert 'TAUX HORAIRES' not in text and 'CADRE CONTRACTUEL' not in text
    assert ('After acceptance' if language == 'en' else 'Après acceptation') in text
    wb = openpyxl.load_workbook(app.generate_excel(data))
    assert wb['ODS']['E47'].value == 2800
    assert wb['ODS']['B7'].value == data['name']
    assert wb['ODS']['B8'].value.endswith(data['addr'])
    assert json.loads(wb['_loi16']['A1'].value)['proposal_kind'] == 'loi16'
    assert data == before


def test_archive_recovery_keeps_subtype_for_conversion():
    data = draft()
    raw = app.generate_excel(data).read()
    found = ('token', 'sender', 'Metra Structure Inc/Offre de service/Structure', 'ODS26-144-STR-LOI.xlsx')
    with patch.object(ods_recovery, '_find_archived_xlsx', return_value=found), \
         patch.object(app, 'download_onedrive_path', return_value=raw):
        ref = ods_recovery._recover_from_xlsx(str(UID), 'ODS26-144-STR-LOI')
    recovered = app.offers_history[str(UID)][ref]['data']
    assert loi.is_loi16(recovered)
    assert recovered['loi16_units'] == 6
    assert recovered['price'] == 2800


def test_checklist_only_after_successful_conversion_and_once(isolated):
    data = draft()
    app.user_data[str(UID)] = data
    with patch.object(loi, '_OLD_CREATE'):
        app._do_create_project(UID, str(UID))
    assert not isolated.called
    def accept(*args):
        data['project_created'] = True
    with patch.object(loi, '_OLD_CREATE', side_effect=accept):
        app._do_create_project(UID, str(UID))
        app._do_create_project(UID, str(UID))
    assert isolated.call_count == 1
    assert 'Déclaration de copropriété' in isolated.call_args.args[1]


def test_other_departments_keep_existing_renderers():
    for department in ('STR', 'CIV', 'GEO'):
        data = {'department': department}
        with patch.object(loi, '_OLD_PDF', return_value='normal-pdf'):
            assert app.generate_pdf(data) == 'normal-pdf'
        with patch.object(loi, '_OLD_EXCEL', return_value='normal-excel'):
            assert app.generate_excel(data) == 'normal-excel'
