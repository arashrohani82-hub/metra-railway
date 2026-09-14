import os
import requests
import app as command_center
import youtube_publish


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
        classify = requests.post(
            f"{ods_url}/router/classify-image",
            headers=_router_headers(),
            files={"image": ("image.jpg", image, "image/jpeg")},
            timeout=90,
        )
        result = _json_or_error(classify, "Router classifier")
        route = result.get("route", "unknown")
        confidence = float(result.get("confidence") or 0)
        if route == "receipt":
            command_center.send_message(chat_id, f"🧠 Smart Router → 📚 Bookkeeping ({confidence:.0%})")
            return _original_receipt_router(user_id, chat_id, file_id)
        if route == "ods":
            command_center.send_message(chat_id, f"🧠 Smart Router → 🧾 ODS / Offers ({confidence:.0%})")
            response = requests.post(
                f"{ods_url}/router/ods-extract",
                headers=_router_headers(),
                data={"user_id": str(user_id)},
                files={"image": ("client-request.jpg", image, "image/jpeg")},
                timeout=120,
            )
            data = _json_or_error(response, "ODS")
            ods = data.get("ods") or {}
            username = command_center.bot_username(command_center.get_bot("ods"))
            keyboard = []
            if username:
                keyboard.append([{"text": "▶️ ادامه در ODS", "url": f"https://t.me/{username}"}])
            keyboard.append([{"text": "🏠 Main menu", "callback_data": "home"}])
            text = (
                "🧾 درخواست مشتری شناسایی شد\n\n"
                f"👤 مشتری: {ods.get('name') or '—'}\n"
                f"📧 ایمیل: {ods.get('email') or '—'}\n"
                f"📞 تلفن: {ods.get('phone') or '—'}\n"
                f"📍 پروژه: {ods.get('addr') or '—'}\n"
                f"🔧 سرویس: {ods.get('service') or '—'}\n"
                f"💰 پیشنهاد اولیه: ${int(ods.get('price') or 0):,} CAD\n"
                f"📄 شماره اولیه: {ods.get('odsNum') or '—'}\n\n"
                "اطلاعات داخل Session ربات ODS ذخیره شد."
            )
            command_center.send_message(chat_id, text, keyboard)
            return
        labels = {"inspection": "🏗 Inspection / Report", "guardian": "🛡 Guardian", "unknown": "❓ نامشخص"}
        command_center.send_message(
            chat_id,
            f"🧠 Smart Router: {labels.get(route, route)} ({confidence:.0%})\nاتصال مستقیم این مسیر در مرحله بعد فعال می‌شود.",
            [[{"text": "🏠 Main menu", "callback_data": "home"}]],
        )
    except Exception as exc:
        command_center.logger.exception("Smart image routing failed")
        command_center.send_message(chat_id, f"❌ Smart Router خطا داد:\n{str(exc)[:260]}")


command_center.route_receipt_photo = smart_route_image


def animation_main_menu():
    return [
        [command_center.bot_open_button("ods", "🧾 ODS / Offers"), command_center.bot_open_button("bookkeeping", "📚 Bookkeeping")],
        [command_center.bot_open_button("guardian", "🛡 Guardian"), command_center.bot_open_button("intelligence", "🌎 Intelligence")],
        [command_center.bot_open_button("language", "🗣 Language"), command_center.bot_open_button("website", "🌐 Website")],
        [command_center.bot_open_button("inspection", "🏗 Inspection / Report")],
        [{"text": "🎬 Arvin Animation", "callback_data": "dashboard"}, {"text": "⚙️ Bots & System", "callback_data": "system"}],
    ]


def youtube_status_text():
    if youtube_publish.youtube_configured():
        privacy = os.getenv("YOUTUBE_DEFAULT_PRIVACY", "unlisted").strip() or "unlisted"
        return f"🟢 YouTube connected · default: {privacy}"
    return "🟡 YouTube needs one-time OAuth connection"


def show_animation_studio(chat_id):
    command_center.send_message(
        chat_id,
        "🎬 ARVIN ANIMATION STUDIO\n\n"
        "کارتون‌های کوتاه آموزشی و آگاهی‌بخش برای Arvin.\n\n"
        "فرآیند:\n"
        "🖼 عکس + 🎯 موضوع → 📝 سناریو → ✅ تأیید → 🎬 انیمیشن → 🔊 صداگذاری → MP4 → 📺 YouTube\n\n"
        + youtube_status_text(),
        [
            [{"text": "➕ New Animation", "callback_data": "anim:new"}],
            [{"text": "📚 My Animations", "callback_data": "anim:library"}, {"text": "⚙️ Settings", "callback_data": "anim:settings"}],
            [{"text": "📺 YouTube", "callback_data": "anim:youtube"}],
            [{"text": "⬅️ Main menu", "callback_data": "home"}],
        ],
    )


def show_animation_settings(chat_id):
    privacy = os.getenv("YOUTUBE_DEFAULT_PRIVACY", "unlisted").strip() or "unlisted"
    command_center.send_message(
        chat_id,
        "⚙️ ARVIN ANIMATION SETTINGS\n\n"
        "🌐 Language: English\n"
        "⏱ Target length: 30–60 sec\n"
        "👦 Main character: Arvin\n"
        f"📺 YouTube privacy: {privacy}\n"
        "🧒 YouTube audience: Made for Kids\n\n"
        "قبل از انتشار، Title / Description / Thumbnail برای تأیید نمایش داده می‌شود.",
        [[{"text": "📺 YouTube status", "callback_data": "anim:youtube"}], [{"text": "⬅️ Back", "callback_data": "dashboard"}]],
    )


def show_youtube(chat_id):
    if youtube_publish.youtube_configured():
        command_center.send_message(
            chat_id,
            "📺 YOUTUBE PUBLISHING\n\n"
            "✅ اتصال آماده است.\n"
            "بعد از ساخته‌شدن MP4، ربات Title، Description و Thumbnail را نشان می‌دهد و فقط با تأیید شما ویدیو را منتشر می‌کند.\n\n"
            "حالت پیش‌فرض انتشار: Unlisted",
            [[{"text": "⬅️ Back", "callback_data": "dashboard"}]],
        )
    else:
        command_center.send_message(
            chat_id,
            "📺 YOUTUBE PUBLISHING\n\n"
            "برای آپلود مستقیم فقط یک اتصال OAuth لازم است.\n"
            "در Railway باید YOUTUBE_CLIENT_ID، YOUTUBE_CLIENT_SECRET و YOUTUBE_REFRESH_TOKEN تنظیم شوند.\n\n"
            "پس از اتصال، انتشار پیش‌فرض Unlisted خواهد بود و بدون تأیید شما Public نمی‌شود.",
            [[{"text": "⬅️ Back", "callback_data": "dashboard"}]],
        )


def publish_final_animation(video_bytes, title, description, tags=None):
    """Called by the animation renderer after the user approves YouTube publishing."""
    return youtube_publish.upload_video(
        video_bytes=video_bytes,
        title=title,
        description=description,
        privacy_status=os.getenv("YOUTUBE_DEFAULT_PRIVACY", "unlisted"),
        tags=tags or ["kids education", "social skills", "school", "Arvin"],
    )


command_center.main_menu = animation_main_menu
command_center.show_dashboard = show_animation_studio

_original_handle_update = command_center.handle_update


def animation_handle_update(data):
    cb = data.get("callback_query") or {}
    action = cb.get("data", "") if cb else ""
    if action.startswith("anim:"):
        actor = cb.get("from") or {}
        chat = (cb.get("message") or {}).get("chat") or {}
        actor_id = actor.get("id")
        chat_id = chat.get("id")
        if not command_center.authorized(actor_id):
            if chat_id:
                command_center.send_message(chat_id, "⛔ This Command Center is private.")
            return
        try:
            command_center.telegram("answerCallbackQuery", {"callback_query_id": cb["id"]})
        except Exception:
            pass
        if action == "anim:new":
            command_center.send_message(
                chat_id,
                "➕ NEW ANIMATION\n\nیک عکس مرجع و موضوع آموزشی را بفرست.\nمثال: Making friends at school / Ask the teacher for help.\n\nقبل از ساخت انیمیشن، سناریو برای تأیید شما نمایش داده می‌شود.",
                [[{"text": "⬅️ Back", "callback_data": "dashboard"}]],
            )
        elif action == "anim:library":
            command_center.send_message(chat_id, "📚 MY ANIMATIONS\n\nویدیوهای نهایی اینجا فهرست می‌شوند.", [[{"text": "⬅️ Back", "callback_data": "dashboard"}]])
        elif action == "anim:settings":
            show_animation_settings(chat_id)
        elif action == "anim:youtube":
            show_youtube(chat_id)
        return
    return _original_handle_update(data)


command_center.handle_update = animation_handle_update
app = command_center.app
