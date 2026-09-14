import os
import requests
import app as command_center


def resilient_bot_status(bot):
    url = command_center.bot_service_url(bot)
    if not url:
        return "⚪ Not connected"
    try:
        response = requests.get(f"{url}/status", timeout=4)
        if response.ok:
            return "🟢 Online"
        if response.status_code in (401, 403, 404):
            root = requests.get(url, timeout=4)
            if root.ok:
                return "🟢 Online"
        return f"🟡 HTTP {response.status_code}"
    except Exception:
        return "🔴 Offline"


command_center.bot_status = resilient_bot_status

_original_bot_open_button = command_center.bot_open_button


def direct_bot_open_button(key, label):
    if key == "language":
        bot = command_center.get_bot(key)
        username = command_center.bot_username(bot) if bot else ""
        if username:
            return {"text": label, "url": f"tg://resolve?domain={username}"}
    return _original_bot_open_button(key, label)


command_center.bot_open_button = direct_bot_open_button

_original_send_message = command_center.send_message


def smart_send_message(chat_id, text, keyboard=None):
    if text == "🧠 عکس دریافت شد؛ در حال ارسال به Bookkeeping…":
        text = "🧠 عکس دریافت شد؛ در حال تحلیل و مسیریابی…"
    return _original_send_message(chat_id, text, keyboard)


command_center.send_message = smart_send_message
_original_receipt_router = command_center.route_receipt_photo


def _ods_url():
    return os.getenv("ODS_SERVICE_URL", "").strip().rstrip("/")


def _router_headers():
    return {"X-Router-Secret": command_center.ROUTER_SHARED_SECRET}


def _json_or_error(response, label):
    try:
        data = response.json()
    except Exception:
        raise RuntimeError(f"{label} HTTP {response.status_code}: non-JSON {response.text[:160]}")
    if not response.ok or not data.get("ok"):
        detail = data.get("detail") or data.get("error") or f"HTTP {response.status_code}"
        raise RuntimeError(f"{label}: {detail}")
    return data


def smart_route_image(user_id, chat_id, file_id):
    ods_url = _ods_url()
    if not ods_url or not command_center.ROUTER_SHARED_SECRET:
        command_center.send_message(chat_id, "⚠️ Smart Router برای ODS هنوز تنظیم نشده.")
        return
    try:
        image = command_center.download_telegram_file(file_id)
        classify = requests.post(f"{ods_url}/router/classify-image", headers=_router_headers(), files={"image": ("image.jpg", image, "image/jpeg")}, timeout=90)
        result = _json_or_error(classify, "Router classifier")
        route = result.get("route", "unknown")
        confidence = float(result.get("confidence") or 0)
        if route == "receipt":
            command_center.send_message(chat_id, f"🧠 Smart Router → 📚 Bookkeeping ({confidence:.0%})")
            return _original_receipt_router(user_id, chat_id, file_id)
        if route == "ods":
            command_center.send_message(chat_id, f"🧠 Smart Router → 🧾 ODS / Offers ({confidence:.0%})")
            response = requests.post(f"{ods_url}/router/ods-extract", headers=_router_headers(), data={"user_id": str(user_id)}, files={"image": ("client-request.jpg", image, "image/jpeg")}, timeout=120)
            data = _json_or_error(response, "ODS")
            ods = data.get("ods") or {}
            username = command_center.bot_username(command_center.get_bot("ods"))
            keyboard = []
            if username:
                keyboard.append([{"text": "▶️ ادامه در ODS", "url": f"https://t.me/{username}"}])
            keyboard.append([{"text": "🏠 Main menu", "callback_data": "home"}])
            text = ("🧾 درخواست مشتری شناسایی شد\n\n" f"👤 مشتری: {ods.get('name') or '—'}\n" f"📧 ایمیل: {ods.get('email') or '—'}\n" f"📞 تلفن: {ods.get('phone') or '—'}\n" f"📍 پروژه: {ods.get('addr') or '—'}\n" f"🔧 سرویس: {ods.get('service') or '—'}\n" f"💰 پیشنهاد اولیه: ${int(ods.get('price') or 0):,} CAD\n" f"📄 شماره اولیه: {ods.get('odsNum') or '—'}\n\n" "اطلاعات داخل Session ربات ODS ذخیره شد.")
            command_center.send_message(chat_id, text, keyboard)
            return
        labels = {"inspection": "🏗 Inspection / Report", "guardian": "🛡 Guardian", "unknown": "❓ نامشخص"}
        command_center.send_message(chat_id, f"🧠 Smart Router: {labels.get(route, route)} ({confidence:.0%})\nاتصال مستقیم این مسیر در مرحله بعد فعال می‌شود.", [[{"text": "🏠 Main menu", "callback_data": "home"}]])
    except Exception as exc:
        command_center.logger.exception("Smart image routing failed")
        command_center.send_message(chat_id, f"❌ Smart Router خطا داد:\n{str(exc)[:260]}")


command_center.route_receipt_photo = smart_route_image

# Repurpose the unused CEO Dashboard slot for Arvin Animation Studio.
def animation_main_menu():
    return [
        [command_center.bot_open_button("ods", "🧾 ODS / Offers"), command_center.bot_open_button("bookkeeping", "📚 Bookkeeping")],
        [command_center.bot_open_button("guardian", "🛡 Guardian"), command_center.bot_open_button("intelligence", "🌎 Intelligence")],
        [command_center.bot_open_button("language", "🗣 Language"), command_center.bot_open_button("website", "🌐 Website")],
        [command_center.bot_open_button("inspection", "🏗 Inspection / Report")],
        [{"text":"🎬 Arvin Animation","callback_data":"dashboard"},{"text":"⚙️ Bots & System","callback_data":"system"}],
    ]


def show_animation_studio(chat_id):
    command_center.send_message(
        chat_id,
        "🎬 ARVIN ANIMATION STUDIO\n\n"
        "کارتون‌های کوتاه آموزشی و آگاهی‌بخش برای Arvin.\n\n"
        "فرآیند:\n"
        "🖼 عکس + 🎯 موضوع → 📝 سناریو → ✅ تأیید → 🎬 انیمیشن → 🔊 صداگذاری → MP4",
        [
            [{"text":"➕ New Animation","callback_data":"anim:new"}],
            [{"text":"📚 My Animations","callback_data":"anim:library"},{"text":"⚙️ Settings","callback_data":"anim:settings"}],
            [{"text":"⬅️ Main menu","callback_data":"home"}],
        ],
    )


command_center.main_menu = animation_main_menu
command_center.show_dashboard = show_animation_studio
app = command_center.app
