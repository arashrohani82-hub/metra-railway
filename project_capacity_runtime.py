"""Live remaining contract value in Telegram, using the invoice list's receipts."""
import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from zoneinfo import ZoneInfo

import app as legacy
import ods_runtime as projects

BUTTON = '💰 Capacité financière'
PREFIX = 'project_capacity:'
PAGE_SIZE = 10
TAX_FACTOR = Decimal('1.14975')


def cents(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def amount(value):
    return f'{cents(value):,.2f}'.replace(',', ' ').replace('.', ',') + ' $'


def capacity(items):
    """Exclude unknown inputs from the subtotal, but report every unknown project."""
    known, unknown, seen = [], [], set()
    for item in items:
        code = str(item.get('name') or '')[:7].upper()
        if code in seen:
            continue
        seen.add(code)
        try:
            contract = float(item.get('contract'))
            fraction = projects._received_fraction(item.get('received_fraction'))
            if not math.isfinite(contract) or contract <= 0 or fraction is None:
                raise ValueError('Missing financial data')
        except (TypeError, ValueError, OverflowError):
            unknown.append(item)
            continue
        net = cents(Decimal(str(contract)) * (1 - Decimal(str(fraction))))
        if net <= 0:
            continue
        known.append({**item, 'code': code, 'contract': cents(contract),
                      'remaining': net, 'tax_included': cents(net * TAX_FACTOR)})
    known.sort(key=lambda row: (-row['remaining'], row['code']))
    total = sum((row['remaining'] for row in known), Decimal('0'))
    return {'projects': known, 'unknown': unknown, 'total': total,
            'tax_included': cents(total * TAX_FACTOR)}


def load_capacity():
    return capacity(projects.projects_awaiting_settlement(
        projects.onedrive_projects(), include_financials=True))


def summary_text(report):
    rows = report['projects']
    top = sum((row['remaining'] for row in rows[:5]), Decimal('0'))
    stamp = datetime.now(ZoneInfo('America/Toronto')).strftime('%d/%m/%Y %H:%M')
    text = (f'💰 <b>Capacité financière des projets</b>\n{stamp} — Montréal\n\n'
            f'<b>Reste à encaisser HT : {amount(report["total"])}</b>\n'
            f'Avec TPS/TVQ estimées : <b>{amount(report["tax_included"])}</b>\n'
            f'{len(rows)} projet(s) avec solde calculable.\n\n'
            f'🎯 Les 5 plus gros soldes : <b>{amount(top)} HT</b>\n')
    for row in rows[:5]:
        text += f'• {row["code"]} : {amount(row["remaining"])} HT\n'
    text += ('\nValeur contractuelle restante après les encaissements enregistrés. '
             'La réalisation du travail et les conditions de paiement déterminent la date de perception. '
             'Ce montant ne représente pas le bénéfice.\n'
             'Les taxes sont une estimation TPS 5 % + TVQ 9,975 %.')
    if report['unknown']:
        text += (f'\n\n⚠️ {len(report["unknown"])} projet(s) hors total : '
                 'montant du contrat ou réception manquants.\n' +
                 ', '.join(escape(str(p.get('name') or '')[:7]) for p in report['unknown'][:40]))
    return text


def show(chat_id, uid, page=0):
    try:
        report = load_capacity()
    except Exception:
        legacy.logger.exception('Project capacity unavailable')
        legacy.tg(chat_id, '❌ Impossible de lire les soldes. Réessayez avec Actualiser.',
                  [[{'text': '🔄 Actualiser', 'callback_data': PREFIX + 'page:0'}]])
        return
    rows = report['projects']
    page = max(0, min(page, max(0, (len(rows) - 1) // PAGE_SIZE)))
    buttons = []
    for i, row in enumerate(rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]):
        buttons.append([{'text': f'{row["code"]} · {amount(row["remaining"])} HT',
                         'callback_data': PREFIX + 'pick:' + row['code']}])
    nav = []
    if page:
        nav.append({'text': '⬅️ Précédent', 'callback_data': PREFIX + f'page:{page - 1}'})
    if (page + 1) * PAGE_SIZE < len(rows):
        nav.append({'text': 'Suivant ➡️', 'callback_data': PREFIX + f'page:{page + 1}'})
    if nav:
        buttons.append(nav)
    buttons.append([{'text': '🔄 Actualiser', 'callback_data': PREFIX + f'page:{page}'}])
    legacy.tg(chat_id, summary_text(report) + f'\n\nProjets par solde décroissant — page {page + 1}.', buttons)


def detail(chat_id, code):
    try:
        report = load_capacity()
        row = next((p for p in report['projects'] if p['code'] == code), None)
        if row is None:
            legacy.tg(chat_id, 'Ce projet est soldé ou ses données sont incomplètes. Actualisez la liste.')
            return
        physical = row.get('physical_fraction')
        progress = f'{physical * 100:g} %' if physical is not None else 'non renseigné'
        text = (f'📁 <b>{escape(str(row["name"]))}</b>\n\n'
                f'Contrat HT : {amount(row["contract"])}\n'
                f'Reçu : {row["received_fraction"] * 100:.1f} %\n'
                f'<b>Solde HT : {amount(row["remaining"])}</b>\n'
                f'Avec TPS/TVQ estimées : {amount(row["tax_included"])}\n'
                f'Avancement du travail enregistré : {progress}\n\n'
                'Vérifier la livraison et les échéances du contrat pour déterminer ce qui peut être encaissé maintenant.')
        legacy.tg(chat_id, text, [[{'text': '⬅️ Tous les soldes', 'callback_data': PREFIX + 'page:0'}]])
    except Exception:
        legacy.logger.exception('Project capacity detail unavailable')
        legacy.tg(chat_id, '❌ Impossible de lire ce projet. Actualisez la liste.')


def install_menu():
    previous = legacy.main_menu
    def menu():
        markup = previous()
        if not any(c.get('text') == BUTTON for row in markup.get('keyboard', []) for c in row):
            markup['keyboard'].append([{'text': BUTTON}])
        return markup
    legacy.main_menu = menu


def handle(update):
    callback = update.get('callback_query') or {}
    message = callback.get('message') or update.get('message') or {}
    data = str(callback.get('data') or '')
    text = str(message.get('text') or '').strip()
    if text not in (BUTTON, '/capacite') and not data.startswith(PREFIX):
        return False
    actor = (callback.get('from') or message.get('from') or {}).get('id')
    chat_id = (message.get('chat') or {}).get('id')
    if actor not in legacy.ALLOWED_USERS:
        legacy.tg(chat_id, '⛔ Ce bot est privé.')
        return True
    if callback:
        try:
            legacy.req.post(f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                            json={'callback_query_id': callback.get('id')}, timeout=3)
        except Exception:
            pass
    if data.startswith(PREFIX + 'pick:'):
        legacy.executor.submit(detail, chat_id, data.split(':', 2)[2])
    else:
        try:
            page = int(data.split(':', 2)[2]) if data else 0
        except (ValueError, IndexError):
            page = 0
        legacy.executor.submit(show, chat_id, str(actor), page)
    return True
