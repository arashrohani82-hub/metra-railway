"""Railway application entrypoint.

Loads the ODS/router Flask application and installs ODS patches before any
auxiliary bot startup work. The Telegram webhook is explicitly rebound to the
final STR/CIV/GEO handler so later runtime monkey-patches cannot bypass it.
"""
import os

from ods_router import app

# Side-effect patches on app.py.
import ods_recovery  # noqa: E402,F401
# Load the established OneDrive invoice selectors before the department router
# captures its fallback handler. Otherwise the Facturation reply button is
# treated as arbitrary client text.
import invoice_control_runtime  # noqa: E402,F401
import ods_runtime as invoice_runtime  # noqa: E402
import department_ods_patch as department_patch  # noqa: E402
import department_contract_templates  # noqa: E402,F401
import justify_pdf_text  # noqa: E402,F401
import department_assumption_questions as department_assumptions  # noqa: E402
import department_storage_fix  # noqa: E402,F401
import email_branding_patch  # noqa: E402,F401

import app as ods_app


def _answer_callback(callback):
    callback_id = (callback or {}).get('id')
    if not callback_id:
        return
    try:
        ods_app.req.post(
            f'https://api.telegram.org/bot{ods_app.BOT_TOKEN}/answerCallbackQuery',
            json={'callback_query_id': callback_id},
            timeout=10,
        )
    except Exception:
        pass


def department_dispatch(update):
    """Protect CIV/GEO flows from falling back to legacy structural questions."""
    callback = (update or {}).get('callback_query') or {}
    cdata = str(callback.get('data') or '')
    message = callback.get('message') or (update or {}).get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    user = callback.get('from') or (update or {}).get('message', {}).get('from') or {}
    uid = str(user.get('id') or chat_id or '')
    data = ods_app.user_data.get(uid, {}) if uid else {}
    code = department_patch._dept(data, uid) if uid else 'STR'

    incoming_text = str(((update or {}).get('message') or {}).get('text') or '')
    if incoming_text in ('🧾 Facturation', '🧾 Facturer un projet') or cdata.startswith('od_invoice_project:'):
        if user.get('id') not in ods_app.ALLOWED_USERS:
            ods_app.tg(chat_id, '⛔ Ce bot est privé.')
            return
        if cdata.startswith('od_invoice_project:'):
            _answer_callback(callback)
            return invoice_runtime.select_onedrive_project(chat_id, uid, cdata.split(':', 1)[1])
        return invoice_runtime.show_onedrive_projects_for_invoice(chat_id, uid)

    if code in ('CIV', 'GEO') and callback:
        if cdata == 'note_none':
            data['special_note'] = ''
            data['special_note_confirmed'] = True
            data.pop('waiting_field', None)
            ods_app.user_data[uid] = data
            ods_app.save_user_data()
            _answer_callback(callback)
            return department_assumptions.ask_next_missing(chat_id, uid)

        if cdata in ('assumption_access_yes', 'assumption_access_no',
                     'assumption_architect_yes', 'assumption_architect_no'):
            # Old structural buttons may still be visible in an in-progress chat.
            # Ignore their value and jump immediately to the correct department flow.
            data['assumption_access'] = False
            data['assumption_access_confirmed'] = True
            data['assumption_architect'] = False
            data['assumption_architect_confirmed'] = True
            ods_app.user_data[uid] = data
            ods_app.save_user_data()
            _answer_callback(callback)
            return department_assumptions.ask_next_missing(chat_id, uid)

    # If a custom special note is being typed in CIV/GEO, finish that common
    # question here and continue directly into discipline-specific confirmations.
    incoming_message = (update or {}).get('message') or {}
    if code in ('CIV', 'GEO') and incoming_message and data.get('waiting_field') == 'special_note':
        text = str(incoming_message.get('text') or '').strip()
        if text:
            data['special_note'] = '' if text.lower() in ('aucune', 'none', 'non') else text
            data['special_note_confirmed'] = True
            data.pop('waiting_field', None)
            ods_app.user_data[uid] = data
            ods_app.save_user_data()
            return department_assumptions.ask_next_missing(chat_id, uid)

    return department_patch.handle_update(update)


# IMPORTANT: app.py's Flask view was registered before the monkey-patch. Rebind
# the registered endpoint itself so /webhook/telegram always dispatches through
# the department-aware handler, rather than relying only on a module global.
def department_webhook():
    if ods_app.WEBHOOK_SECRET:
        supplied = ods_app.request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not ods_app.hmac.compare_digest(supplied, ods_app.WEBHOOK_SECRET):
            return 'forbidden', 403
    data = ods_app.request.get_json(force=True, silent=True)
    if data:
        ods_app.executor.submit(department_dispatch, data)
    return 'ok', 200


app.view_functions['webhook'] = department_webhook
ods_app.logger.warning('RUNTIME CONFIRMED: /webhook/telegram -> DEPARTMENT STR/CIV/GEO HANDLER')
ods_app.logger.warning('RUNTIME CONFIRMED: CIV/GEO assumption guard active before legacy structural prompts')

import household_bot

railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
if railway_domain:
    household_bot.PUBLIC_URL = f'https://{railway_domain}'

household_bot.init_household_bot(app)
setup_result = household_bot.configure()
household_bot.logger.warning(
    'HOUSEHOLD BOT webhook setup ok=%s url=%s description=%s',
    setup_result.get('ok'),
    f'{household_bot.PUBLIC_URL}/webhook/household' if household_bot.PUBLIC_URL else 'missing',
    (setup_result.get('webhook') or {}).get('description', ''),
)

# Load this last so no later runtime layer can restore the old email signature.
import final_email_branding  # noqa: E402,F401
