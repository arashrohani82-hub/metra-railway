import json
import os
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

try:
    import anthropic
except Exception:
    anthropic = None

app = Flask(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.getenv("SETUP_SECRET", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest").strip()

ALLOWED_USERS = {
    int(x.strip()) for x in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",") if x.strip().isdigit()
}

SESSIONS = {}
LIBRARY = []

TOPICS = {
    "friends": "Making friends at school",
    "help": "What to do when someone bothers you: tell a teacher and then tell a parent",
    "sharing": "Sharing and taking turns",
    "feelings": "Naming and expressing feelings calmly",
    "confidence": "Trying something new with confidence",
    "safety": "Everyday school safety and asking a trusted adult for help",
}


def tg(method, payload=None):
    if not BOT_TOKEN:
        return None
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", payload)


def answer_callback(callback_id):
    try:
        tg("answerCallbackQuery", {"callback_query_id": callback_id})
    except Exception:
        pass


def authorized(user_id):
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def main_menu():
    return [
        [{"text": "🎬 New Animation", "callback_data": "bt:new"}],
        [{"text": "📚 My Animations", "callback_data": "bt:library"}],
        [{"text": "📡 Social Channels", "callback_data": "bt:social"}, {"text": "⚙️ Settings", "callback_data": "bt:settings"}],
    ]


def topic_menu():
    return [
        [{"text": "🤝 Making Friends", "callback_data": "bt:topic:friends"}, {"text": "🧑‍🏫 Ask for Help", "callback_data": "bt:topic:help"}],
        [{"text": "🧸 Sharing", "callback_data": "bt:topic:sharing"}, {"text": "💛 Feelings", "callback_data": "bt:topic:feelings"}],
        [{"text": "🌟 Confidence", "callback_data": "bt:topic:confidence"}, {"text": "🛡 Safety", "callback_data": "bt:topic:safety"}],
        [{"text": "❌ Cancel", "callback_data": "bt:cancel"}],
    ]


def scenario_fallback(topic):
    title = TOPICS.get(topic, "A BrightTale Lesson")
    return {
        "title": title,
        "lesson": title,
        "duration_seconds": 45,
        "language": "English",
        "scenes": [
            {"scene": 1, "duration": 6, "visual": "A cheerful child arrives at school.", "narration": "A new day can be a chance to connect.", "dialogue": "Hi!", "sfx": "soft school ambience"},
            {"scene": 2, "duration": 7, "visual": "The child notices another child nearby.", "narration": "Start with a small, friendly step.", "dialogue": "Can I play with you?", "sfx": "gentle playful sounds"},
            {"scene": 3, "duration": 8, "visual": "The children play together.", "narration": "Taking turns and being kind helps friendship grow.", "dialogue": "Your turn!", "sfx": "happy play"},
            {"scene": 4, "duration": 8, "visual": "A small problem happens and the child feels upset.", "narration": "If something feels wrong, you do not have to solve it alone.", "dialogue": "I feel hurt.", "sfx": "music softens"},
            {"scene": 5, "duration": 8, "visual": "The child talks to a trusted teacher.", "narration": "Tell a trusted adult clearly what happened.", "dialogue": "Please help me.", "sfx": "calm reassuring tone"},
            {"scene": 6, "duration": 8, "visual": "At home, the child tells a parent and smiles.", "narration": "And always tell your parent too. Asking for help is a brave choice.", "dialogue": "I told my teacher, and now I am telling you.", "sfx": "warm ending music"},
        ],
        "takeaway": "Be kind, speak up, and ask a trusted adult for help when you need it.",
    }


def generate_scenario(topic):
    if not ANTHROPIC_API_KEY or anthropic is None:
        return scenario_fallback(topic)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Create a 40-60 second child-friendly animated social-learning story in English for ages 4-7.
Topic: {TOPICS.get(topic, topic)}
Tone: warm, simple, positive, non-scary, actionable.
Use a generic child character; do not include private personal details.
Return ONLY valid JSON with this schema:
{{"title":"...","lesson":"...","duration_seconds":45,"language":"English","scenes":[{{"scene":1,"duration":6,"visual":"...","narration":"...","dialogue":"...","sfx":"..."}}],"takeaway":"..."}}
Use 6-8 scenes. If the story involves a problem with another child, teach: calmly tell the teacher/trusted adult, then tell a parent at home."""
    msg = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1800,
        temperature=0.5,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    return json.loads(raw)


def format_scenario(s):
    lines = [f"📝 {s.get('title','BrightTale Story')}", "", f"🎯 Lesson: {s.get('lesson','')}", f"⏱ {s.get('duration_seconds',45)} sec", ""]
    for sc in s.get("scenes", []):
        lines.append(f"Scene {sc.get('scene')}: {sc.get('visual','')}")
        if sc.get("dialogue"):
            lines.append(f"💬 {sc.get('dialogue')}")
        if sc.get("narration"):
            lines.append(f"🎙 {sc.get('narration')}")
        lines.append("")
    lines.append(f"⭐ Takeaway: {s.get('takeaway','')}")
    return "\n".join(lines)[:3900]


def social_status_text():
    youtube = bool(os.getenv("YOUTUBE_CLIENT_ID") and os.getenv("YOUTUBE_CLIENT_SECRET") and os.getenv("YOUTUBE_REFRESH_TOKEN"))
    instagram = os.getenv("INSTAGRAM_CONNECTED", "false").lower() == "true"
    tiktok = os.getenv("TIKTOK_CONNECTED", "false").lower() == "true"
    mark = lambda x: "🟢 Connected" if x else "⚪ Not connected"
    return (
        "📡 BRIGHTTALE CHANNELS\n\n"
        f"▶️ YouTube: {mark(youtube)}\n"
        f"📸 Instagram: {mark(instagram)}\n"
        f"🎵 TikTok: {mark(tiktok)}\n\n"
        "Final publishing always waits for creator approval."
    )


def handle_callback(cb):
    data = cb.get("data", "")
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    user_id = (cb.get("from") or {}).get("id")
    answer_callback(cb.get("id"))
    if not chat_id or not authorized(user_id):
        return

    if data == "bt:new":
        SESSIONS[user_id] = {"stage": "await_photo", "created_at": datetime.now(timezone.utc).isoformat()}
        send(chat_id, "🖼 Send one reference image for the main character.\n\nAfter that, I’ll ask you to choose the lesson/topic.", [[{"text": "❌ Cancel", "callback_data": "bt:cancel"}]])
        return
    if data == "bt:library":
        mine = [x for x in LIBRARY if x.get("user_id") == user_id]
        if not mine:
            send(chat_id, "📚 No animations yet. Your approved projects will appear here.", [[{"text": "🎬 New Animation", "callback_data": "bt:new"}]])
        else:
            lines = ["📚 MY ANIMATIONS", ""] + [f"• {x.get('title')} — {x.get('status')}" for x in mine[-10:]]
            send(chat_id, "\n".join(lines), main_menu())
        return
    if data == "bt:social":
        send(chat_id, social_status_text(), [[{"text": "⬅️ Home", "callback_data": "bt:home"}]])
        return
    if data == "bt:settings":
        send(chat_id, "⚙️ SETTINGS\n\nLanguage: English\nFormat: 9:16 vertical\nTarget duration: 40–60 sec\nPublishing: approval required\nBrand: BrightTale Kids", [[{"text": "⬅️ Home", "callback_data": "bt:home"}]])
        return
    if data == "bt:home":
        send(chat_id, "✨ BRIGHTTALE KIDS\nLittle stories. Big life lessons.", main_menu())
        return
    if data == "bt:cancel":
        SESSIONS.pop(user_id, None)
        send(chat_id, "Cancelled.", main_menu())
        return
    if data.startswith("bt:topic:"):
        session = SESSIONS.get(user_id)
        if not session or not session.get("photo_file_id"):
            send(chat_id, "Please start a new animation and send the reference image first.", main_menu())
            return
        topic = data.split(":", 2)[2]
        session["topic"] = topic
        send(chat_id, "🧠 Creating the scenario…")
        try:
            scenario = generate_scenario(topic)
        except Exception:
            scenario = scenario_fallback(topic)
        session["scenario"] = scenario
        session["stage"] = "scenario_review"
        send(chat_id, format_scenario(scenario), [
            [{"text": "✅ Approve", "callback_data": "bt:approve"}, {"text": "🔄 Regenerate", "callback_data": "bt:regen"}],
            [{"text": "❌ Cancel", "callback_data": "bt:cancel"}],
        ])
        return
    if data == "bt:regen":
        session = SESSIONS.get(user_id)
        if not session or not session.get("topic"):
            return
        send(chat_id, "🔄 Generating another version…")
        try:
            scenario = generate_scenario(session["topic"])
        except Exception:
            scenario = scenario_fallback(session["topic"])
        session["scenario"] = scenario
        send(chat_id, format_scenario(scenario), [
            [{"text": "✅ Approve", "callback_data": "bt:approve"}, {"text": "🔄 Regenerate", "callback_data": "bt:regen"}],
            [{"text": "❌ Cancel", "callback_data": "bt:cancel"}],
        ])
        return
    if data == "bt:approve":
        session = SESSIONS.get(user_id)
        if not session or not session.get("scenario"):
            return
        s = session["scenario"]
        job = {
            "user_id": user_id,
            "title": s.get("title", "BrightTale Story"),
            "topic": session.get("topic"),
            "status": "Approved — awaiting production provider",
            "created_at": session.get("created_at"),
        }
        LIBRARY.append(job)
        session["stage"] = "approved"
        send(chat_id, "✅ Scenario approved.\n\n🎬 Next stage: generate scenes → animate → voice → captions → MP4.\nAfter the MP4 is ready, you’ll get: Publish All / YouTube / Instagram + TikTok / Save only.", [[{"text": "📚 My Animations", "callback_data": "bt:library"}, {"text": "🏠 Home", "callback_data": "bt:home"}]])
        return


def handle_message(message):
    chat_id = (message.get("chat") or {}).get("id")
    user_id = (message.get("from") or {}).get("id")
    if not chat_id or not authorized(user_id):
        return
    text = (message.get("text") or "").strip()
    if text in ("/start", "/menu"):
        send(chat_id, "✨ BRIGHTTALE KIDS\nLittle stories. Big life lessons.\n\nCreate short educational animations and publish them to YouTube, Instagram and TikTok.", main_menu())
        return
    session = SESSIONS.get(user_id)
    photos = message.get("photo") or []
    if session and session.get("stage") == "await_photo" and photos:
        session["photo_file_id"] = photos[-1].get("file_id")
        session["stage"] = "await_topic"
        send(chat_id, "✅ Reference image saved for this project.\n\nChoose the lesson:", topic_menu())
        return
    if session and session.get("stage") == "await_photo":
        send(chat_id, "Please send an image first, or cancel.", [[{"text": "❌ Cancel", "callback_data": "bt:cancel"}]])
        return
    send(chat_id, "Choose an option:", main_menu())


@app.get("/status")
def status():
    return jsonify({"ok": True, "service": "brighttale-kids", "brand": "BrightTale Kids"})


@app.get("/setup")
def setup():
    if not SETUP_SECRET or request.args.get("key") != SETUP_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not PUBLIC_URL or not WEBHOOK_SECRET or not BOT_TOKEN:
        return jsonify({"ok": False, "error": "PUBLIC_URL, WEBHOOK_SECRET and TELEGRAM_BOT_TOKEN are required"}), 400
    webhook_url = f"{PUBLIC_URL}/telegram/webhook/{WEBHOOK_SECRET}"
    result = tg("setWebhook", {"url": webhook_url, "allowed_updates": ["message", "callback_query"]})
    return jsonify({"ok": True, "webhook": webhook_url, "telegram": result})


@app.post("/telegram/webhook/<secret>")
def telegram_webhook(secret):
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        return jsonify({"ok": False}), 403
    update = request.get_json(silent=True) or {}
    try:
        if update.get("callback_query"):
            handle_callback(update["callback_query"])
        elif update.get("message"):
            handle_message(update["message"])
    except Exception as exc:
        app.logger.exception("BrightTale update failed: %s", exc)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
