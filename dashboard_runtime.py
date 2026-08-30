import io
import logging
from datetime import datetime

import openpyxl
import requests

import invoice_control_runtime as control

app = control.app
legacy = control.legacy
logger = logging.getLogger(__name__)


def _amount(value):
    if value in (None, ''):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace('$', '').replace(' ', '')
    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return 0.0


def _date(value):
    if isinstance(value, datetime):
        return value
    if hasattr(value, 'year') and hasattr(value, 'month'):
        return datetime(value.year, value.month, getattr(value, 'day', 1))
    text = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def _status(value):
    raw = str(value or 'In process').strip().lower()
    aliases = {
        'accept': 'Accept', 'accepted': 'Accept', 'accepté': 'Accept',
        'in process': 'In process', 'in progress': 'In process',
        'hold': 'Hold', 'on hold': 'Hold',
        'refused': 'Refused', 'rejected': 'Refused',
        'closed': 'Closed', 'close': 'Closed',
    }
    return aliases.get(raw, str(value or 'In process').strip().title())


def dashboard_metrics(workbook, period='month', marketing=False, now=None):
    """Aggregate management and source-attribution KPIs from List.xlsx."""
    now = now or datetime.now()
    sheet_name = f'data {now.year}'
    if sheet_name not in workbook.sheetnames:
        raise RuntimeError(f'onglet {sheet_name} introuvable dans List.xlsx')
    ws = workbook[sheet_name]
    headers = {
        str(cell.value or '').strip(): cell.column
        for cell in ws[1] if cell.value is not None
    }
    required = ('Description', 'Price($)', 'Date', 'Status', 'Accepted Price', 'Source')
    missing = [name for name in required if name not in headers]
    if missing:
        raise RuntimeError('colonnes manquantes dans List.xlsx : ' + ', '.join(missing))

    if period == 'previous':
        end = datetime(now.year, now.month, 1)
        start = datetime(now.year - 1, 12, 1) if now.month == 1 else datetime(now.year, now.month - 1, 1)
        label = start.strftime('%B %Y')
    elif period == 'year':
        start, end = datetime(now.year, 1, 1), datetime(now.year + 1, 1, 1)
        label = str(now.year)
    else:
        start = datetime(now.year, now.month, 1)
        end = datetime(now.year + 1, 1, 1) if now.month == 12 else datetime(now.year, now.month + 1, 1)
        label = start.strftime('%B %Y')

    rows = []
    for row in range(2, ws.max_row + 1):
        description = str(ws.cell(row, headers['Description']).value or '').strip()
        sent_at = _date(ws.cell(row, headers['Date']).value)
        if not description or not sent_at or not (start <= sent_at < end):
            continue
        status = _status(ws.cell(row, headers['Status']).value)
        price = _amount(ws.cell(row, headers['Price($)']).value)
        accepted_price = _amount(ws.cell(row, headers['Accepted Price']).value)
        if status == 'Accept' and accepted_price <= 0:
            accepted_price = price
        rows.append({
            'date': sent_at, 'status': status, 'price': price,
            'accepted_price': accepted_price,
            'source': str(ws.cell(row, headers['Source']).value or 'Non indiqué').strip() or 'Non indiqué',
        })

    statuses = {name: 0 for name in ('Accept', 'In process', 'Hold', 'Refused', 'Closed')}
    sources = {}
    for item in rows:
        statuses[item['status']] = statuses.get(item['status'], 0) + 1
        source = sources.setdefault(item['source'], {
            'offers': 0, 'accepted': 0, 'quoted': 0.0, 'revenue': 0.0,
        })
        source['offers'] += 1
        source['quoted'] += item['price']
        if item['status'] == 'Accept':
            source['accepted'] += 1
            source['revenue'] += item['accepted_price']

    total = len(rows)
    accepted = statuses.get('Accept', 0)
    stale = [item for item in rows if item['status'] == 'In process' and (now - item['date']).days >= 14]
    return {
        'period_label': label, 'marketing': marketing, 'offers': total,
        'quoted': sum(item['price'] for item in rows), 'accepted': accepted,
        'revenue': sum(item['accepted_price'] for item in rows if item['status'] == 'Accept'),
        'conversion': accepted / total if total else 0.0, 'statuses': statuses,
        'stale_count': len(stale), 'stale_value': sum(item['price'] for item in stale),
        'sources': sorted(
            sources.items(),
            key=lambda entry: (entry[1]['revenue'], entry[1]['accepted'], entry[1]['offers']),
            reverse=True,
        ),
    }


def _money(value):
    return f"{value:,.0f} $".replace(',', ' ')


def format_dashboard(metrics):
    title = '📣 Marketing' if metrics['marketing'] else '📊 Tableau de bord'
    text = [
        f"{title} — {metrics['period_label']}", '',
        f"📝 Offres : {metrics['offers']}  |  {_money(metrics['quoted'])}",
        f"✅ Acceptées : {metrics['accepted']}  |  {_money(metrics['revenue'])}",
        f"🎯 Taux de conversion : {metrics['conversion']:.1%}",
        f"🔄 Pipeline : {metrics['statuses'].get('In process', 0)} en cours  |  {metrics['statuses'].get('Hold', 0)} en attente",
        f"❌ Perdues : {metrics['statuses'].get('Refused', 0)} refusées  |  {metrics['statuses'].get('Closed', 0)} fermées",
        f"⏰ Relances +14 jours : {metrics['stale_count']}  |  {_money(metrics['stale_value'])}",
    ]
    if metrics['sources']:
        text.extend(['', '📣 Performance par source :'])
        for name, source in metrics['sources'][:10 if metrics['marketing'] else 5]:
            rate = source['accepted'] / source['offers'] if source['offers'] else 0
            text.append(
                f"• {name}: {source['offers']} offres | {source['accepted']} acceptées"
                f" | {rate:.0%} | {_money(source['revenue'])}"
            )
    else:
        text.extend(['', 'Aucune offre pour cette période.'])
    if metrics['marketing']:
        text.extend(['', 'ℹ️ Attribution basée sur la colonne Source de List.xlsx.'])
    return '\n'.join(text)


def dashboard_buttons(marketing=False):
    view = 'marketing' if marketing else 'summary'
    return [
        [
            {'text': '📅 Ce mois', 'callback_data': f'ods_dashboard:{view}:month'},
            {'text': '◀️ Mois précédent', 'callback_data': f'ods_dashboard:{view}:previous'},
        ],
        [
            {'text': '🗓 Année', 'callback_data': f'ods_dashboard:{view}:year'},
            {'text': '📣 Marketing', 'callback_data': 'ods_dashboard:marketing:year'},
        ],
    ]


def show_dashboard(chat_id, period='month', marketing=False):
    try:
        config = legacy.microsoft_email_config()
        token = legacy.graph_access_token()
        workbook = openpyxl.load_workbook(io.BytesIO(legacy.download_onedrive_path(
            token, config['EMAIL_SENDER'], legacy.ODS_LIST_PATH,
        )), data_only=True)
        metrics = dashboard_metrics(workbook, period, marketing)
        legacy.tg(chat_id, format_dashboard(metrics), dashboard_buttons(marketing))
    except Exception as exc:
        logger.exception('ODS dashboard generation failed')
        legacy.tg(chat_id, f"❌ Tableau de bord indisponible : {exc}")


_previous_handle_update = legacy.handle_update


def handle_update_dashboard(data):
    msg = data.get('message') or {}
    cb = data.get('callback_query') or {}
    actor_id = (cb.get('from') or msg.get('from') or {}).get('id')
    chat_id = ((cb.get('message') or {}).get('chat') or {}).get('id') if cb else (msg.get('chat') or {}).get('id')
    if msg and str(msg.get('text') or '').strip() == '📊 Tableau de bord':
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, '⛔ Ce bot est privé.')
            return
        legacy.executor.submit(show_dashboard, chat_id, 'month', False)
        return
    cdata = str(cb.get('data') or '')
    if cdata.startswith('ods_dashboard:'):
        if actor_id not in legacy.ALLOWED_USERS:
            legacy.tg(chat_id, '⛔ Ce bot est privé.')
            return
        try:
            requests.post(
                f'https://api.telegram.org/bot{legacy.BOT_TOKEN}/answerCallbackQuery',
                json={'callback_query_id': cb.get('id')}, timeout=3,
            )
        except Exception:
            pass
        _, view, period = cdata.split(':', 2)
        legacy.executor.submit(show_dashboard, chat_id, period, view == 'marketing')
        return
    return _previous_handle_update(data)


legacy.handle_update = handle_update_dashboard
logger.info('ODS MANAGEMENT AND MARKETING DASHBOARD ACTIVE')
