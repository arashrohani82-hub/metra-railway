import os
import tempfile
from unittest.mock import patch

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')
os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='metra-list-balance-'))

import app
import ods_runtime as ods


def render(items, outstanding=True):
    with patch.object(ods, 'onedrive_projects', return_value=items), \
         patch.object(ods, 'projects_awaiting_settlement', return_value=items), \
         patch.object(app, 'save_user_data'), patch.object(app, 'tg') as tg:
        ods.show_onedrive_projects_for_invoice(1, 'list-balance', only_outstanding=outstanding)
    return tg.call_args.args


def test_same_project_opens_from_either_column_and_total_uses_received_fraction():
    _, text, buttons = render([
        {'name': 'P26-049-TMN-Inspection', 'contract': 1800, 'received_fraction': .25},
        {'name': 'P26-042-FIG-Fenêtres', 'contract': 800, 'received_fraction': .9}])
    assert '1 430,00 $' in text
    assert '1 644,14 $' in text
    assert '<b>' not in text and '</b>' not in text
    assert 'Colonne gauche' not in text
    assert len(text) < 250
    assert buttons[0][0]['text'].startswith('P26-049 | 25% | TMN')
    assert buttons[0][1]['text'] == '1 350 $'
    assert buttons[1][1]['text'] == '80 $'
    assert buttons[0][0]['callback_data'] == buttons[0][1]['callback_data']
    assert app.user_data['list-balance']['invoice_project_choices']['1']['folder'] == 'P26-049-TMN-Inspection'


def test_total_includes_projects_beyond_button_limit_and_unknown_is_explicit():
    items = [{'name': f'P26-{i:03d}-ABC', 'contract': 1000, 'received_fraction': 0}
             for i in range(1, 32)]
    items.append({'name': 'P26-032-Unknown', 'contract': None, 'received_fraction': 0})
    _, text, buttons = render(items)
    assert '31 000,00 $' in text
    assert '1 projet(s) hors total' in text
    assert len(buttons) == 31  # 30 projects and new-invoice action
    _, _, unknown_buttons = render([items[-1]])
    assert unknown_buttons[0][1]['text'] == 'Solde n/d'


def test_new_invoice_all_projects_keeps_one_column():
    _, text, buttons = render([{'name': 'P26-001-ABC'}], outstanding=False)
    assert text == '🧾 Nouvelle facture — tous les projets'
    assert len(buttons[0]) == 1
