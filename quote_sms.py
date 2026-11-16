"""Send one quotation notice immediately after Microsoft accepts its email.

Reservations are durable and intentionally never retried automatically after an
ambiguous network result: a timeout may already have created a Twilio message.
"""
import hashlib
import os
import re
import sqlite3
from pathlib import Path

import requests

from offer_identity import reference


def normalize_mobile(value):
    raw = str(value or '').strip()
    if not re.fullmatch(r'\+?[0-9 ().-]+', raw):
        return ''
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        digits = '1' + digits
    return '+' + digits if re.fullmatch(r'1[2-9]\d{2}[2-9]\d{6}', digits) else ''


def notify_quote(data, data_dir):
    """Return an operator status, never the Twilio token or response body.

    Enabled only after production credentials are configured. The caller must
    call this solely after Graph sendMail returns HTTP 202.
    """
    if os.environ.get('TWILIO_SMS_ENABLED', '').lower() not in ('true', '1', 'yes'):
        return {'status': 'disabled'}
    sid = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
    token = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    sender = normalize_mobile(os.environ.get('TWILIO_FROM_NUMBER'))
    if not re.fullmatch(r'AC[0-9a-fA-F]{32}', sid) or not token or not sender:
        return {'status': 'not_configured'}
    destination = normalize_mobile(data.get('phone'))
    if not destination:
        return {'status': 'missing_phone'}
    offer = reference(data.get('odsNum'))
    if not offer:
        return {'status': 'missing_reference'}

    body = (
        f'Metra Consultation: votre offre {offer} a ete envoyee par courriel. '
        'Verifiez aussi les indesirables. STOP pour arreter.'
    )
    if data.get('language') == 'en':
        body = (
            f'Metra Consultation: your quote {offer} was emailed to you. '
            'Please also check your junk folder. Reply STOP to opt out.'
        )
    key = hashlib.sha256((offer + '|' + destination).encode()).hexdigest()
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    db_path = str(Path(data_dir) / 'quote_sms.sqlite3')
    with sqlite3.connect(db_path, timeout=5) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS notices (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, sid TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        inserted = db.execute(
            'INSERT OR IGNORE INTO notices(id, status) VALUES (?, ?)',
            (key, 'reserved'),
        ).rowcount
    if not inserted:
        return {'status': 'duplicate'}

    try:
        response = requests.post(
            f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json',
            auth=(sid, token),
            data={'From': sender, 'To': destination, 'Body': body},
            timeout=(5, 15),
            allow_redirects=False,
        )
        result = response.json()
        message_sid = str(result.get('sid') or '')
        if response.status_code == 201 and re.fullmatch(r'SM[0-9a-fA-F]{32}', message_sid):
            status = str(result.get('status') or 'accepted')
            if status not in ('accepted', 'queued', 'sending', 'sent', 'delivered', 'failed', 'undelivered'):
                status = 'accepted'
            outcome = {'status': status, 'sid': message_sid}
        else:
            code = str(result.get('code') or '')
            outcome = {'status': 'failed', 'code': code if code.isdigit() else ''}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        outcome = {'status': 'unknown'}
    with sqlite3.connect(db_path, timeout=5) as db:
        db.execute('UPDATE notices SET status=?, sid=? WHERE id=?',
                   (outcome['status'], outcome.get('sid'), key))
    return outcome


def operator_message(outcome):
    status = (outcome or {}).get('status')
    if status in ('accepted', 'queued', 'sending', 'sent', 'delivered'):
        return '📱 Notification SMS transmise à Twilio. La livraison dépend de l’opérateur.'
    if status == 'duplicate':
        return '📱 SMS déjà traité pour cette offre et ce numéro; aucun doublon envoyé.'
    if status == 'missing_phone':
        return '⚠️ Courriel envoyé. SMS non envoyé : numéro mobile client manquant ou invalide.'
    if status == 'disabled':
        return ''
    return '⚠️ Courriel envoyé. SMS non confirmé; vérifier Twilio avant toute nouvelle tentative.'
