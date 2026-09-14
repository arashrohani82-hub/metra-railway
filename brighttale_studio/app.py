import hmac
import os
from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.getenv("SETUP_SECRET", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ALLOWED_USERS = {
    int(x.strip()) for x in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",") if x.strip().isdigit()
}

SESSIONS = {}

TOPICS = {
    "friends": "Making friends",
    "help": "Asking an adult for help",
    "feelings": "Understanding feelings",
    "sharing": "Sharing and taking turns",
    "safety": "School safety",
    "custom": "Custom lesson",
}


def tg(method, payload):
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", payload)


def home(chat_id):
    send(
        chat_id,
        "✨ BRIGHTTALE KIDS\nLittle stories. Big life lessons.\n\nیک بخش را انتخاب کن:",
        [
            [{"text": "➕ New Story", "callback_data": "new"}],
            [{"text": "📚 My Stories", "callback_data": "library"}, {"text": "📣 Publish", "callback_data": "publish"}],
            [{"text": "⚙️ Settings", "callback_data": "settings"}],
        ],
    )


def topic_menu(chat_id):
    rows = [
        [{"text": "🤝 Making Friends", "callback_data": "topic:friends"}],
        [{"text": "🧑‍🏫 Ask for Help", "callback_data": "topic:help"}],
        [{"text": "💛 Feelings", "callback_data": "topic:feelings"}],
        [{"text": "🧸 Sharing", "callback_data": "topic:sharing"}],
        [{"text": "🛡 School Safety", "callback_data": "topic:safety"}],
        [{"text": "✏️ Custom", "callback_data": "topic:custom"}],
        [{"text": "⬅️ Home", "callback_data": "home"}],
    ]
    send(chat_id, "موضوع آموزشی را انتخاب کن:", rows)


def draft_script(topic):
    label = TOPICS.get(topic, topic)
    return (
        f"🎬 Draft Story — {label}\n\n"
        "Scene 1 — A simple school situation.\n"
        "Scene 2 — The child notices how they feel.\n"
        "Scene 3 — They try a kind, clear first step.\n"
        "Scene 4 — If the problem continues, they ask a trusted adult for help.\n"
        "Scene 5 — The situation gets resolved safely.\n"
        "Scene 6 — Takeaway: You can be kind, brave, and ask for help.\n\n"
        "این نسخه MVP است؛ موتور داستان‌سازی AI بعداً به همین مرحله وصل می‌شود."
    )


def show_publish_menu(chat_id):
    send(
        chat_id,
        "📣 PUBLISH\n\nبعد از آماده‌شدن MP4، انتشار فقط با تأیید نهایی انجام می‌شود.",
        [
            [{"text": "🌐 Publish All", "callback_data": "pub:all"}],
            [{"text": "▶️ YouTube", "callback_data": "pub:youtube"}],
            [{"text": "📸 Instagram", "callback_data": "pub:instagram"}],
            [{"text": "🎵 TikTok", "callback_data": "pub:tiktok"}],
            [{"text": "💾 Save Only", "callback_data": "pub:save"}],
            [{"text": "⬅️ Home", "callback_data": "home"}],
        ],
    )


def handle_callback(user_id, chat_id, action):
    session = SESSIONS.setdefault(user_id, {})
    if action == "home":
        home(chat_id)
    elif action == "new":
        session.clear()
        session["state"] = "choosing_topic"
        topic_menu(chat_id)
    elif action.startswith("topic:"):
        topic = action.split(":", 1)[1]
        session["topic"] = topic
        session["state"] = "awaiting_photo"
        send(
            chat_id,
            f"موضوع: {TOPICS.get(topic, topic)}\n\nحالا اگر عکس مرجع داری بفرست. اگر نمی‌خواهی عکس بدهی، Skip را بزن.",
            [[{"text": "⏭ Skip photo", "callback_data": "photo:skip"}], [{"text": "❌ Cancel", "callback_data": "home"}]],
        )
    elif action == "photo:skip":
        session["state"] = "script_ready"
        send(
            chat_id,
            draft_script(session.get("topic", "custom")),
            [[{"text": "✅ Approve Script", "callback_data": "script:approve"}, {"text": "🔄 Regenerate", "callback_data": "script:regen"}], [{"text": "❌ Cancel", "callback_data": "home"}]],
        )
    elif action == "script:regen":
        send(chat_id, draft_script(session.get("topic", "custom")), [[{"text": "✅ Approve Script", "callback_data": "script:approve"}, {"text": "🔄 Regenerate", "callback_data": "script:regen"}]])
    elif action == "script:approve":
        session["state"] = "approved"
        send(
            chat_id,
            "✅ سناریو تأیید شد.\n\nمرحله بعد Render Pipeline است: Scene generation → animation → voice → captions → MP4.",
            [[{"text": "🎬 Start Render", "callback_data": "render:start"}], [{"text": "⬅️ Home", "callback_data": "home"}]],
        )
    elif action == "render:start":
        session["state"] = "render_pending"
        send(
            chat_id,
            "🎬 Render Pipeline آماده اتصال است. برای تولید واقعی باید سرویس‌های IMAGE_RENDER_URL / VIDEO_RENDER_URL / TTS_URL به Railway وصل شوند.\n\nبعد از تولید MP4، Preview و دکمه‌های انتشار فعال می‌شوند.",
            [[{"text": "📣 Publish Menu", "callback_data": "publish"}], [{"text": "⬅️ Home", "callback_data": "home"}]],
        )
    elif action == "publish":
        show_publish_menu(chat_id)
    elif action.startswith("pub:"):
        target = action.split(":", 1)[1]
        if target == "save":
            send(chat_id, "💾 Save-only انتخاب شد. هیچ چیزی منتشر نمی‌شود.", [[{"text": "⬅️ Home", "callback_data": "home"}]])
        else:
            send(
                chat_id,
                f"🔐 {target.upper()} publishing آماده اتصال است، ولی تا وقتی OAuth/API همان حساب در Railway تنظیم نشده باشد چیزی منتشر نمی‌شود.\n\nبرای نسخه تجاری، هر کاربر OAuth خودش را خواهد داشت.",
                [[{"text": "⬅️ Publish", "callback_data": "publish"}], [{"text": "🏠 Home", "callback_data": "home"}]],
            )
    elif action == "library":
        send(chat_id, "📚 My Stories\n\nهنوز پروژه ذخیره‌شده‌ای در دیتابیس نداریم. این بخش در مرحله Database فعال می‌شود.", [[{"text": "⬅️ Home", "callback_data": "home"}]])
    elif action == "settings":
        send(
            chat_id,
            "⚙️ SETTINGS\n\nLanguage: English\nFormat: 9:16\nYouTube: Unlisted by default\nApproval before publishing: ON\nAI disclosure: ON",
            [[{"text": "⬅️ Home", "callback_data": "home"}]],
        )


def handle_message(msg):
    actor = msg.get("from") or {}
    user_id = actor.get("id")
    chat_id = (msg.get("chat") or {}).get("id")
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        send(chat_id, "⛔ Private beta.")
        return
    text = (msg.get("text") or "").strip()
    if text in ("/start", "/menu", "/home"):
        home(chat_id)
        return
    if msg.get("photo"):
        session = SESSIONS.setdefault(user_id, {})
        session["reference_photo_file_id"] = msg["photo"][-1]["file_id"]
        session["state"] = "script_ready"
        send(
            chat_id,
            "🖼 عکس مرجع ذخیره شد.\n\n" + draft_script(session.get("topic", "custom")),
            [[{"text": "✅ Approve Script", "callback_data": "script:approve"}, {"text": "🔄 Regenerate", "callback_data": "script:regen"}], [{"text": "❌ Cancel", "callback_data": "home"}]],
        )
        return
    home(chat_id)


@app.route("/")
def index():
    return jsonify({"service": "brighttale-kids-studio", "status": "ok"})


@app.route("/status")
def status():
    return jsonify({"status": "ok", "brand": "BrightTale Kids", "channels": ["youtube", "instagram", "tiktok"]})


@app.route("/webhook/telegram", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            return "forbidden", 403
    data = request.get_json(silent=True) or {}
    cb = data.get("callback_query")
    if cb:
        actor = cb.get("from") or {}
        user_id = actor.get("id")
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        if ALLOWED_USERS and user_id not in ALLOWED_USERS:
            send(chat_id, "⛔ Private beta.")
            return "ok", 200
        try:
            tg("answerCallbackQuery", {"callback_query_id": cb.get("id")})
        except Exception:
            pass
        handle_callback(user_id, chat_id, cb.get("data", ""))
    elif data.get("message"):
        handle_message(data["message"])
    return "ok", 200


@app.route("/setup")
def setup():
    supplied = request.headers.get("X-Setup-Secret", "") or request.args.get("key", "")
    if not SETUP_SECRET or not hmac.compare_digest(supplied, SETUP_SECRET):
        return "forbidden", 403
    if not PUBLIC_URL:
        return jsonify({"error": "PUBLIC_URL is required"}), 400
    webhook_payload = {
        "url": f"{PUBLIC_URL}/webhook/telegram",
        "allowed_updates": ["message", "callback_query"],
    }
    if WEBHOOK_SECRET:
        webhook_payload["secret_token"] = WEBHOOK_SECRET
    webhook_result = tg("setWebhook", webhook_payload)
    command_result = tg(
        "setMyCommands",
        {"commands": [
            {"command": "start", "description": "Open BrightTale Kids"},
            {"command": "menu", "description": "Main menu"},
        ]},
    )
    return jsonify({"ok": True, "webhook": webhook_result, "commands": command_result})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
