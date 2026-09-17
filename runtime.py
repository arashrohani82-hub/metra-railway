"""Railway application entrypoint.

Loads the ODS/router Flask application and installs ODS patches before any
auxiliary bot startup work, so the Telegram ODS webhook always sees the final
STR/CIV/GEO handler.
"""
import os

from ods_router import app

# These are side-effect patches on app.py. They MUST load before auxiliary bot
# configuration so nothing can delay or bypass the final ODS handler.
import ods_recovery  # noqa: E402,F401
import department_ods_patch  # noqa: E402,F401

import app as ods_app
ods_app.logger.warning("RUNTIME CONFIRMED: ODS RECOVERY + DEPARTMENT STR/CIV/GEO LOADED")

import household_bot

# Prefer Railway's live public domain for the household Telegram webhook.
railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if railway_domain:
    household_bot.PUBLIC_URL = f"https://{railway_domain}"

household_bot.init_household_bot(app)

# Configure synchronously once at startup. setWebhook is idempotent.
setup_result = household_bot.configure()
household_bot.logger.warning(
    "HOUSEHOLD BOT webhook setup ok=%s url=%s description=%s",
    setup_result.get("ok"),
    f"{household_bot.PUBLIC_URL}/webhook/household" if household_bot.PUBLIC_URL else "missing",
    (setup_result.get("webhook") or {}).get("description", ""),
)
