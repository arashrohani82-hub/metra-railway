import logging

import requests

import fixed_ods_app as base

app = base.app
logger = logging.getLogger(__name__)

PUBLIC_URL = "https://web-production-c7adbe.up.railway.app"
WEBHOOK_URL = f"{PUBLIC_URL}/webhook/telegram"


def force_telegram_webhook():
    token = getattr(base.legacy, "BOT_TOKEN", None)
    if not token:
        logger.error("ODS RUNTIME: TELEGRAM_BOT_TOKEN is missing")
        return

    try:
        me = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        ).json()
        if me.get("ok"):
            result = me.get("result") or {}
            logger.info(
                "ODS RUNTIME TELEGRAM BOT: ok=true username=@%s id=%s",
                result.get("username", ""),
                result.get("id", ""),
            )
        else:
            logger.error(
                "ODS RUNTIME TELEGRAM BOT: ok=false error=%s",
                me.get("description", "unknown Telegram error"),
            )
            return

        payload = {
            "url": WEBHOOK_URL,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }
        secret = getattr(base.legacy, "WEBHOOK_SECRET", "")
        if secret:
            payload["secret_token"] = secret

        result = requests.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json=payload,
            timeout=15,
        ).json()
        logger.info(
            "ODS RUNTIME SET WEBHOOK: ok=%s url=%s description=%s",
            result.get("ok"),
            WEBHOOK_URL,
            result.get("description", ""),
        )
    except Exception:
        logger.exception("ODS RUNTIME WEBHOOK SETUP FAILED")


force_telegram_webhook()
