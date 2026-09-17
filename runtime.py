"""Railway application entrypoint.

Loads the ODS/router Flask application and installs ODS patches before any
auxiliary bot startup work. The Telegram webhook is explicitly rebound to the
final STR/CIV/GEO handler so later runtime monkey-patches cannot bypass it.
"""
import os

from ods_router import app

# Side-effect patches on app.py.
import ods_recovery  # noqa: E402,F401
import department_ods_patch as department_patch  # noqa: E402

import app as ods_app

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
        ods_app.executor.submit(department_patch.handle_update, data)
    return 'ok', 200

app.view_functions['webhook'] = department_webhook
ods_app.logger.warning('RUNTIME CONFIRMED: /webhook/telegram -> DEPARTMENT STR/CIV/GEO HANDLER')

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
