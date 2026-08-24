import hmac
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metra-command-center")

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=4)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.environ.get("SETUP_SECRET", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
ROUTER_SHARED_SECRET = os.environ.get("ROUTER_SHARED_SECRET", "").strip()
ALLOWED_USERS = {
    int(value.strip())
    for value in os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").split(",")
    if value.strip().isdigit()
}

PENDING_PROJECT_USERS = set()

BOTS = [
    {"key":"ods","name":"ODS / Offers","emoji":"🧾","username_env":"ODS_BOT_USERNAME","service_url_env":"ODS_SERVICE_URL","repo":"arashrohani82-hub/metra-railway"},
    {"key":"bookkeeping","name":"Bookkeeping / Financial","emoji":"📚","username_env":"BOOKKEEPING_BOT_USERNAME","service_url_env":"BOOKKEEPING_SERVICE_URL","repo":"arashrohani82-hub/metra-financial-bot"},
    {"key":"guardian","name":"Guardian","emoji":"🛡","username_env":"GUARDIAN_BOT_USERNAME","service_url_env":"GUARDIAN_SERVICE_URL","repo":"arashrohani82-hub/metra-guardian"},
    {"key":"intelligence","name":"CEO Intelligence","emoji":"🌎","username_env":"INTELLIGENCE_BOT_USERNAME","service_url_env":"INTELLIGENCE_SERVICE_URL","repo":"arashrohani82-hub/metra-ceo-intelligence-agent"},
    {"key":"language","name":"Language Coach","emoji":"🗣","username_env":"LANGUAGE_BOT_USERNAME","service_url_env":"LANGUAGE_SERVICE_URL","repo":"arashrohani82-hub/metra-language-coach-bot"},
    {"key":"website","name":"Website Manager","emoji":"🌐","username_env":"WEBSITE_BOT_USERNAME","service_url_env":"WEBSITE_SERVICE_URL","repo":"arashrohani82-hub/metra-website-manager-bot"},
    {"key":"inspection","name":"Inspection / Report","emoji":"🏗","username_env":"INSPECTION_BOT_USERNAME","service_url_env":"INSPECTION_SERVICE_URL","repo":"arashrohani82-hub/bsf-inspection-bot"},
]


def telegram(method, payload):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    response = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=20)
    if response.status_code != 200:
        logger.error("Telegram %s failed: %s", method, response.text[:300])
    response.raise_for_status()
    return response.json()


def send_message(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return telegram("sendMessage", payload)


def main_menu():
    return [
        [{"text":"🧾 ODS / Offers","callback_data":"open:ods"},{"text":"📚 Bookkeeping","callback_data":"open:bookkeeping"}],
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
        response = requests.get(f"{url}/status", timeout=5, allow_redirects=True)
        if response.ok:
            return "🟢 Online"
        if response.status_code in (401, 403, 404, 405):
            root = requests.get(url, timeout=5, allow_redirects=True)
            if root.status_code < 500:
                return "🟢 Online"
        return f"🟡 HTTP {response.status_code}"
    except requests.RequestException:
        return "🔴 Offline"


def show_home(chat_id):
    send_message(chat_id, "🏢 METRA COMMAND CENTER\n\nمرکز مدیریت ربات‌ها و عملیات Metra\nیک بخش را انتخاب کنید:", main_menu())


def show_bot(chat_id, key):
    bot = get_bot(key)
    if not bot:
        send_message(chat_id, "❌ Bot not found.")
        return
    username = bot_username(bot)
    keyboard = []
    if username:
        keyboard.append([{"text":f"▶️ Open {bot['name']}","url":f"https://t.me/{username}"}])
    keyboard.append([{"text":"📊 Check status","callback_data":f"status:{key}"}])
    keyboard.append([{"text":"⬅️ Main menu","callback_data":"home"}])
    send_message(chat_id, f"{bot['emoji']} {bot['name']}\n\nStatus: {bot_status(bot)}\nRepo: {bot['repo']}\nTelegram: {'@' + username if username else 'Not connected yet'}", keyboard)


def show_system(chat_id):
    lines = ["⚙️ BOTS & SYSTEM", ""]
    for bot in BOTS:
        lines.append(f"{bot['emoji']} {bot['name']} — {bot_status(bot)}")
    send_message(chat_id, "\n".join(lines), [[{"text":"🔄 Refresh","callback_data":"system"}],[{"text":"⬅️ Main menu","callback_data":"home"}]])


def show_dashboard(chat_id):
    connected = sum(1 for bot in BOTS if bot_service_url(bot))
    online = sum(1 for bot in BOTS if bot_service_url(bot) and bot_status(bot).startswith("🟢"))
    send_message(chat_id, f"📊 CEO DASHBOARD — MVP\n\n🤖 Registered bots: {len(BOTS)}\n🔗 Connected services: {connected}/{len(BOTS)}\n🟢 Online now: {online}/{len(BOTS)}\n\nSmart Router: 🧾 Receipt → Bookkeeping فعال", [[{"text":"⬅️ Main menu","callback_data":"home"}]])


def authorized(actor_id):
    return actor_id in ALLOWED_USERS


def download_telegram_file(file_id):
    meta = telegram("getFile", {"file_id": file_id})
    path = meta["result"]["file_path"]
    response = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=30)
    response.raise_for_status()
    return response.content


def bookkeeping_url():
    return os.environ.get("BOOKKEEPING_SERVICE_URL", "").strip().rstrip("/")


def router_headers():
    return {"X-Router-Secret": ROUTER_SHARED_SECRET}


def route_receipt_photo(user_id, chat_id, file_id):
    url = bookkeeping_url()
    if not url or not ROUTER_SHARED_SECRET:
        send_message(chat_id, "⚠️ Smart Router هنوز کامل تنظیم نشده: BOOKKEEPING_SERVICE_URL / ROUTER_SHARED_SECRET")
        return
    try:
        image = download_telegram_file(file_id)
        response = requests.post(
            f"{url}/router/receipt",
            headers=router_headers(),
            data={"user_id": str(user_id)},
            files={"image": ("receipt.jpg", image, "image/jpeg")},
            timeout=120,
        )
        data = response.json()
        if not response.ok or not data.get("ok"):
            raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
        if data.get("duplicate"):
            send_message(chat_id, f"⚠️ این رسید قبلاً ثبت شده است.\n{data.get('merchant','')} — ${float(data.get('total') or 0):.2f}")
            return
        receipt = data["receipt"]
        text = (
            "🧠 Smart Router → 📚 Bookkeeping\n\n"
            "🧾 اطلاعات رسید\n"
            f"فروشنده: {receipt.get('merchant','—')}\n"
            f"تاریخ: {receipt.get('date','—')}\n"
            f"قبل از مالیات: ${float(receipt.get('subtotal') or 0):.2f}\n"
            f"GST: ${float(receipt.get('gst') or 0):.2f}\n"
            f"QST: ${float(receipt.get('qst') or 0):.2f}\n"
            f"جمع: ${float(receipt.get('total') or 0):.2f} {receipt.get('currency','CAD')}\n\n"
            "این هزینه مربوط به شرکت است یا شخصی؟"
        )
        send_message(chat_id, text, [[{"text":"🏢 شرکت","callback_data":"bk:type:company"},{"text":"👤 شخصی","callback_data":"bk:type:personal"}],[{"text":"❌ لغو","callback_data":"bk:cancel"}]])
    except Exception as exc:
        logger.exception("Receipt routing failed")
        send_message(chat_id, f"❌ پردازش رسید انجام نشد: {type(exc).__name__}")


def bookkeeping_action(user_id, action):
    response = requests.post(
        f"{bookkeeping_url()}/router/action",
        headers=router_headers(),
        json={"user_id": user_id, "action": action},
        timeout=30,
    )
    data = response.json()
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


def handle_bookkeeping_callback(user_id, chat_id, action):
    try:
        if action == "cancel":
            bookkeeping_action(user_id, "cancel")
            PENDING_PROJECT_USERS.discard(user_id)
            send_message(chat_id, "لغو شد.", [[{"text":"🏠 Main menu","callback_data":"home"}]])
            return
        if action.startswith("type:"):
            data = bookkeeping_action(user_id, action)
            categories = data.get("categories") or []
            keyboard = [[{"text": cat, "callback_data": f"bk:category:{i}"}] for i, cat in enumerate(categories)]
            keyboard.append([{"text":"❌ لغو","callback_data":"bk:cancel"}])
            send_message(chat_id, "دسته هزینه را انتخاب کن:", keyboard)
            return
        if action.startswith("category:"):
            data = bookkeeping_action(user_id, action)
            if data.get("state") == "saved":
                send_message(chat_id, "✅ هزینه شخصی با موفقیت ثبت شد.", [[{"text":"🏠 Main menu","callback_data":"home"}]])
            elif data.get("state") == "enter_project":
                PENDING_PROJECT_USERS.add(user_id)
                send_message(chat_id, "کد پروژه را بنویس؛ مثلاً ODS26-076.\nاگر هزینه عمومی شرکت است دکمه زیر را بزن.", [[{"text":"🏢 هزینه عمومی شرکت","callback_data":"bk:project:none"}],[{"text":"❌ لغو","callback_data":"bk:cancel"}]])
            return
        if action == "project:none":
            bookkeeping_action(user_id, action)
            PENDING_PROJECT_USERS.discard(user_id)
            send_message(chat_id, "✅ هزینه عمومی شرکت ثبت شد.", [[{"text":"🏠 Main menu","callback_data":"home"}]])
    except Exception as exc:
        logger.exception("Bookkeeping callback failed")
        send_message(chat_id, f"❌ عملیات Bookkeeping انجام نشد: {type(exc).__name__}")


def save_project_code(user_id, chat_id, text):
    try:
        response = requests.post(
            f"{bookkeeping_url()}/router/project",
            headers=router_headers(),
            json={"user_id": user_id, "project_code": text},
            timeout=30,
        )
        data = response.json()
        if not response.ok or not data.get("ok"):
            raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
        PENDING_PROJECT_USERS.discard(user_id)
        send_message(chat_id, f"✅ هزینه برای پروژه {data.get('project_code')} ثبت شد.", [[{"text":"🏠 Main menu","callback_data":"home"}]])
    except Exception as exc:
        logger.exception("Project code save failed")
        send_message(chat_id, f"❌ ثبت کد پروژه انجام نشد: {type(exc).__name__}")


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
        if action.startswith("bk:"):
            handle_bookkeeping_callback(actor_id, chat_id, action[3:])
        elif action == "home": show_home(chat_id)
        elif action == "system": show_system(chat_id)
        elif action == "dashboard": show_dashboard(chat_id)
        elif action.startswith("open:"): show_bot(chat_id, action.split(":",1)[1])
        elif action.startswith("status:"):
            key = action.split(":",1)[1]
            bot = get_bot(key)
            if bot:
                send_message(chat_id, f"{bot['emoji']} {bot['name']}\nStatus: {bot_status(bot)}", [[{"text":"⬅️ Back","callback_data":f"open:{key}"}]])
        return

    text = (msg.get("text") or "").strip()
    if msg.get("photo"):
        send_message(chat_id, "🧠 عکس دریافت شد؛ در حال ارسال به Bookkeeping…")
        file_id = msg["photo"][-1]["file_id"]
        executor.submit(route_receipt_photo, actor_id, chat_id, file_id)
    elif actor_id in PENDING_PROJECT_USERS and text and not text.startswith("/"):
        save_project_code(actor_id, chat_id, text)
    elif text in ("/start","/menu","/home"): show_home(chat_id)
    elif text in ("/status","/system"): show_system(chat_id)
    elif text == "/dashboard": show_dashboard(chat_id)
    else:
        send_message(chat_id, "🧠 Smart Router فعال است. فعلاً مسیر Receipt → Bookkeeping مستقیم شده؛ مسیرهای ODS، Guardian و Inspection در مرحله بعد اضافه می‌شوند.", [[{"text":"🏠 Main menu","callback_data":"home"}]])


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
    commands_result = telegram("setMyCommands", {"commands":[{"command":"start","description":"Open Metra Command Center"},{"command":"dashboard","description":"CEO dashboard"},{"command":"status","description":"Bots and system status"},{"command":"menu","description":"Main menu"}]})
    return jsonify({"ok":bool(webhook_result.get("ok") and commands_result.get("ok")),"webhook":webhook_result,"commands":commands_result})


@app.route("/status")
def status():
    return jsonify({"status":"ok","service":"metra-command-center","registered_bots":len(BOTS),"smart_router":"receipt-bookkeeping"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
