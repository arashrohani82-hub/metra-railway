"""Railway application entrypoint.

Loads the existing ODS/router Flask application, then registers auxiliary bots
that share the same Railway web service.
"""
import os

from ods_router import app
import ods_recovery  # patches ODS conversion search with OneDrive recovery
import household_bot

# Prefer Railway's live public domain for the household Telegram webhook. This
# avoids an older PUBLIC_URL/ODS_PUBLIC_URL silently pointing Telegram at a
# stale endpoint after a deployment.
railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if railway_domain:
    household_bot.PUBLIC_URL = f"https://{railway_domain}"

household_bot.init_household_bot(app)

# Configure synchronously once at startup so a deploy immediately repairs the
# Home Shopping Manager webhook. init_household_bot also has a background
# setup attempt; setWebhook is idempotent, so the extra call is safe.
setup_result = household_bot.configure()
household_bot.logger.warning(
    "HOUSEHOLD BOT webhook setup ok=%s url=%s description=%s",
    setup_result.get("ok"),
    f"{household_bot.PUBLIC_URL}/webhook/household" if household_bot.PUBLIC_URL else "missing",
    (setup_result.get("webhook") or {}).get("description", ""),
)
