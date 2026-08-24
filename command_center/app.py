import hmac
import os
import logging
from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metra-command-center")

app = Flask(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.environ.get("SETUP_SECRET", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
ALLOWED_USERS = {
    int(value.strip())
    for value in os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").split(",")
    if value.strip().isdigit()
}

BOTS = [
    {"key":"ods","name":"ODS / Offers","emoji":"🧾","username_env":"ODS_BOT_USERNAME","service_url_env":"ODS_SERVICE_URL","repo":"arashrohani82-hub/metra-railway"},
    {"key":"finance","name":"Finance","emoji":"💰","username_env":"FINANCIAL_BOT_USERNAME","service_url_env":"FINANCIAL_SERVICE_URL","repo":"arashrohani82-hub/metra-financial-bot"},
    {"key":"guardian","name":"Guardian","emoji":"🛡","username_env":"GUARDIAN_BOT_USERNAME","service_url_env":"GUARDIAN_SERVICE_URL","repo":"arashrohani82-hub/metra-guardian"},
    {"key":"intelligence","name":"CEO Intelligence","emoji":"🌎","username_env":"INTELLIGENCE_BOT_USERNAME","service_url_env":"INTELLIGENCE_SERVICE_URL","repo":"arashrohani82-hub/metra-ceo-intelligence-agent"},
    {"key":"language","name":"Language Coach","emoji":"🗣","username_env":"LANGUAGE_BOT_USERNAME","service_url_env":"LANGUAGE_SERVICE_URL","repo":"arashrohani82-hub/metra-language-coach-bot"},
    {"key":"website","name":"Website Manager","emoji":"🌐","username_env":"WEBSITE_BOT_USERNAME","service_url_env":"WEBSITE_SERVICE_URL","repo":"arashrohani82-hub/metra-website-manager-bot"},
    {"key":"inspection","name":"Inspection / Report","emoji":"🏗","username_env":"INSPECTION_BOT_USERNAME","service_url_env":"INSPECTION_SERVICE_URL","repo":"arashrohani82-hub/bsf-inspection-bot"},
]


def telegram(method, payload):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=15)
    if response.status_code != 200:
        logger.error("Telegram %s failed: %s", method, response.text[:300])
    return response.json()


def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return telegram("sendMessage", payload)


def main_menu():
    return [
        [{"text":"🧾 ODS / Offers","callback_data":"open:ods"},{"text":"💰 Finance","callback_data":"open:finance"}],
        [{"text":"🛡 Guardian","callback_data":"open:guardian"},{"text":"🌎 Intelligence","callback_data":"open:intelligence"}],
        [{"text":"🗣 Language","callback_data":"open:language"},{"text":"🌐 Website","callback_data":"open:website"}],
        [{"text":"🏗 Inspection / Report","callback_data":"open:inspection"}],
        [{"text":"📊 CEO Dashboard","callback_data":"dashboard"},{"text":"⚙️ Bots & System","callback_data":"system"}],
    ]


def get_bot(key):
    return next((bot for bot in BOTS if bot["key"] == key), None)


def bot_username(bot):
    return os.environ.get(bot["username_env"], "").strip().lstrip("@")


def bot_service_url(bot):
    return os.environ.get(bot["service_url_env"], "").strip().rstrip("/")


def bot_status(bot):
    url = bot_service_url(bot)
    if not url:
        return "⚪ Not connected"
    try:
        response = requests.get(f"{url}/status", timeout=4, allow_redirects=True)
        if response.ok:
            return "🟢 Online"
        if response.status_code in (401, 403, 404, 405):
            root = requests.get(url, timeout=4, allow_redirects=True)
            if root.status_code < 500:
                return "🟢 Online"
        return f"🟡 HTTP {response.status_code}"
    except requests.RequestException:
        return "🔴 Offline"


def show_home(chat_id):
    send_message(chat_id,"🏢 METRA COMMAND CENTER\n\nمرکز مدیریت ربات‌ها و عملیات Metra\nیک بخش را انتخاب کنید:",main_menu())


def show_bot(chat_id, key):
    bot = get_bot(key)
    if not bot:
        send_message(chat_id, "❌ Bot not found.")
        return
    username = bot_username(bot)
    status = bot_status(bot)
    keyboard = []
    if username:
        keyboard.append([{"text":f"▶️ Open {bot['name']}","url":f"https://t.me/{username}"}])
    keyboard.append([{"text":"📊 Check status","callback_data":f"status:{key}"}])
    keyboard.append([{"text":"⬅️ Main menu","callback_data":"home"}])
    send_message(chat_id,f"{bot['emoji']} {bot['name']}\n\nStatus: {status}\nRepo: {bot['repo']}\nTelegram: {'@' + username if username else 'Not connected yet'}",keyboard)


def show_system(chat_id):
    lines = ["⚙️ BOTS & SYSTEM", ""]
    for bot in BOTS:
        lines.append(f"{bot['emoji']} {bot['name']} — {bot_status(bot)}")
    send_message(chat_id,"\n".join(lines),[[{"text":"🔄 Refresh","callback_data":"system"}],[{"text":"⬅️ Main menu","callback_data":"home"}]])


def show_dashboard(chat_id):
    online = 0
    connected = 0
    for bot in BOTS:
        if bot_service_url(bot):
            connected += 1
            if bot_status(bot).startswith("🟢"):
                online += 1
    send_message(chat_id,"📊 CEO DASHBOARD — MVP\n\n"f"🤖 Registered bots: {len(BOTS)}\n"f"🔗 Connected services: {connected}/{len(BOTS)}\n"f"🟢 Online now: {online}/{len(BOTS)}\n\n""مرحله بعد: اتصال پروژه‌ها، فاکتورها، ایمیل‌ها و KPIهای شرکت به همین داشبورد.",[[{"text":"⬅️ Main menu","callback_data":"home"}]])


def authorized(actor_id):
    return actor_id in ALLOWED_USERS


def handle_update(data):
    msg = data.get("message") or {}
    cb = data.get("callback_query") or {}
    actor = cb.get("from") if cb else msg.get("from")
    if not actor:
        return
    actor_id = actor.get("id")
    chat = (cb.get("message") or {}).get("chat") if cb else msg.get("chat")
    chat_id = (chat or {}).get("id")
    if not authorized(actor_id):
        if chat_id:
            send_message(chat_id, "⛔ This Command Center is private.")
        return
    if cb:
        try:
            telegram("answerCallbackQuery", {"callback_query_id": cb["id"]})
        except Exception:
            pass
        action = cb.get("data", "")
        if action == "home": show_home(chat_id)
        elif action == "system": show_system(chat_id)
        elif action == "dashboard": show_dashboard(chat_id)
        elif action.startswith("open:"): show_bot(chat_id, action.split(":",1)[1])
        elif action.startswith("status:"):
            key = action.split(":",1)[1]
            bot = get_bot(key)
            if bot:
                send_message(chat_id,f"{bot['emoji']} {bot['name']}\nStatus: {bot_status(bot)}",[[{"text":"⬅️ Back","callback_data":f"open:{key}"}]])
        return
    text = (msg.get("text") or "").strip()
    if text in ("/start","/menu","/home"): show_home(chat_id)
    elif text in ("/status","/system"): show_system(chat_id)
    elif text == "/dashboard": show_dashboard(chat_id)
    else:
        send_message(chat_id,"این نسخه اول Command Center است. فعلاً از منو استفاده کنید؛ Router هوشمند در مرحله بعد اضافه می‌شود.",[[{"text":"🏠 Main menu","callback_data":"home"}]])


def setup_access():
    supplied = request.headers.get("X-Setup-Secret", "") or request.args.get("key", "")
    return bool(SETUP_SECRET) and hmac.compare_digest(supplied, SETUP_SECRET)


@app.route("/")
def index():
    return jsonify({"service":"metra-command-center","status":"ok"})


@app.route("/webhook/telegram", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            return "forbidden", 403
    data = request.get_json(force=True, silent=True) or {}
    handle_update(data)
    return "ok", 200


@app.route("/setup")
def setup():
    if not setup_access():
        return "forbidden", 403
    public_url = PUBLIC_URL
    if not public_url:
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
        public_url = f"https://{domain}" if domain else ""
    if not public_url:
        return jsonify({"error":"PUBLIC_URL is required"}), 400
    webhook_payload = {"url":f"{public_url}/webhook/telegram","allowed_updates":["message","callback_query"]}
    if WEBHOOK_SECRET:
        webhook_payload["secret_token"] = WEBHOOK_SECRET
    webhook_result = telegram("setWebhook", webhook_payload)
    commands_result = telegram("setMyCommands",{"commands":[{"command":"start","description":"Open Metra Command Center"},{"command":"dashboard","description":"CEO dashboard"},{"command":"status","description":"Bots and system status"},{"command":"menu","description":"Main menu"}]})
    return jsonify({"ok":bool(webhook_result.get("ok") and commands_result.get("ok")),"webhook":webhook_result,"commands":commands_result})


@app.route("/status")
def status():
    return jsonify({"status":"ok","service":"metra-command-center","registered_bots":len(BOTS)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
