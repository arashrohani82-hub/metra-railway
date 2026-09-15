"""Button-only Telegram bot for household shopping and consumption tracking.

The bot shares the existing Railway web process, but uses its own Telegram
token, webhook, allow-list, and persistent data file.  Nothing is registered
unless HOUSEHOLD_BOT_TOKEN is configured.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import jsonify, request


logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("HOUSEHOLD_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("HOUSEHOLD_WEBHOOK_SECRET", "").strip()
SETUP_SECRET = os.environ.get(
    "HOUSEHOLD_SETUP_SECRET", os.environ.get("SETUP_SECRET", "")
).strip()
PUBLIC_URL = os.environ.get(
    "HOUSEHOLD_PUBLIC_URL",
    os.environ.get("PUBLIC_URL", os.environ.get("ODS_PUBLIC_URL", "")),
).strip().rstrip("/")
if not PUBLIC_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    PUBLIC_URL = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()}"

ALLOWED_USERS = {
    int(value.strip())
    for value in os.environ.get(
        "HOUSEHOLD_ALLOWED_TELEGRAM_USER_IDS",
        os.environ.get("ALLOWED_TELEGRAM_USER_IDS", ""),
    ).split(",")
    if value.strip().isdigit()
}

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DATA_FILE = DATA_DIR / "household_purchases.json"


CATEGORIES = {
    "dairy": ("🥛 لبنیات و صبحانه", [
        "شیر", "ماست", "پنیر", "کره", "تخم‌مرغ", "نان", "غلات صبحانه",
    ]),
    "produce": ("🍎 میوه و سبزیجات", [
        "موز", "سیب", "پرتقال", "توت‌فرنگی", "خیار", "گوجه", "سیب‌زمینی",
        "پیاز", "سبزیجات", "سالاد",
    ]),
    "protein": ("🍗 گوشت و پروتئین", [
        "مرغ", "گوشت", "ماهی", "تن ماهی", "حبوبات",
    ]),
    "pantry": ("🧺 مواد غذایی", [
        "برنج", "ماکارونی", "روغن", "آرد", "شکر", "نمک", "قهوه", "چای",
        "رب گوجه", "دستمال سفره",
    ]),
    "drinks": ("🧃 نوشیدنی", [
        "آب معدنی", "آبمیوه", "نوشابه", "آب گازدار",
    ]),
    "cleaning": ("🧽 نظافت خانه", [
        "مایع ظرفشویی", "قرص ماشین ظرفشویی", "مایع لباسشویی", "نرم‌کننده لباس",
        "مایع دستشویی", "پاک‌کننده سطوح", "کیسه زباله", "دستمال کاغذی",
        "دستمال توالت",
    ]),
    "personal": ("🧴 بهداشت شخصی", [
        "شامپو", "صابون", "خمیردندان", "مسواک", "دئودورانت", "تیغ اصلاح",
    ]),
    "arvin": ("🧒 وسایل آروین", [
        "میان‌وعده مدرسه", "آبمیوه آروین", "دستمال مرطوب", "لوازم مدرسه",
    ]),
}


def _item_id(category: str, index: int) -> str:
    return f"{category}-{index}"


CATALOG = {
    _item_id(category, index): {"name": name, "category": category}
    for category, (_, names) in CATEGORIES.items()
    for index, name in enumerate(names)
}


class HouseholdStore:
    def __init__(self, path: Path = DATA_FILE):
        self.path = Path(path)
        self.lock = threading.RLock()

    @staticmethod
    def blank():
        return {"shopping": {}, "purchases": [], "sessions": {}}

    def load(self):
        with self.lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                payload = self.blank()
            if not isinstance(payload, dict):
                payload = self.blank()
            payload.setdefault("shopping", {})
            payload.setdefault("purchases", [])
            payload.setdefault("sessions", {})
            return payload

    def save(self, payload):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)

    def add_to_list(self, item_id, quantity=1):
        with self.lock:
            payload = self.load()
            row = dict(payload["shopping"].get(item_id) or {})
            row["quantity"] = int(row.get("quantity") or 0) + int(quantity)
            row["added_at"] = row.get("added_at") or _now_iso()
            payload["shopping"][item_id] = row
            self.save(payload)
            return row

    def remove_from_list(self, item_id):
        with self.lock:
            payload = self.load()
            payload["shopping"].pop(item_id, None)
            self.save(payload)

    def record_purchase(self, item_id, quantity=1):
        with self.lock:
            payload = self.load()
            item = CATALOG[item_id]
            payload["purchases"].append({
                "item_id": item_id,
                "name": item["name"],
                "quantity": int(quantity),
                "purchased_at": _now_iso(),
            })
            payload["purchases"] = payload["purchases"][-3000:]
            payload["shopping"].pop(item_id, None)
            self.save(payload)


STORE = HouseholdStore()


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_day(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def consumption_stats(payload, today=None):
    """Return learned median purchase interval and next expected date per item."""
    today = today or date.today()
    grouped = {}
    for row in payload.get("purchases", []):
        item_id = row.get("item_id")
        purchased = _parse_day(row.get("purchased_at"))
        if item_id in CATALOG and purchased:
            grouped.setdefault(item_id, []).append(purchased)

    result = {}
    for item_id, days in grouped.items():
        unique_days = sorted(set(days))
        intervals = [
            (current - previous).days
            for previous, current in zip(unique_days, unique_days[1:])
            if (current - previous).days > 0
        ]
        average_days = int(round(statistics.median(intervals))) if intervals else None
        next_date = unique_days[-1] + timedelta(days=average_days) if average_days else None
        result[item_id] = {
            "purchases": len(days),
            "average_days": average_days,
            "last_date": unique_days[-1],
            "next_date": next_date,
            "due": bool(next_date and next_date <= today + timedelta(days=3)),
        }
    return result


def _main_menu():
    return {
        "keyboard": [
            [{"text": "🛒 لیست خرید"}, {"text": "➕ افزودن کالا"}],
            [{"text": "✅ ثبت خرید"}, {"text": "⚠️ رو به اتمام"}],
            [{"text": "📊 روند مصرف"}, {"text": "📜 تاریخچه خرید"}],
            [{"text": "🏠 منوی اصلی"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "یکی از دکمه‌ها را انتخاب کنید…",
    }


def _inline(rows):
    return {"inline_keyboard": rows}


def _category_keyboard(action="category"):
    rows = []
    items = list(CATEGORIES.items())
    for index in range(0, len(items), 2):
        row = []
        for key, (label, _) in items[index:index + 2]:
            row.append({"text": label, "callback_data": f"{action}:{key}"})
        rows.append(row)
    rows.append([{"text": "⬅️ بازگشت", "callback_data": "home"}])
    return _inline(rows)


def _telegram(method, **payload):
    if not BOT_TOKEN:
        return {"ok": False, "description": "HOUSEHOLD_BOT_TOKEN is missing"}
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=20
    )
    try:
        return response.json()
    except ValueError:
        return {"ok": False, "description": response.text[:200]}


def _send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _telegram("sendMessage", **payload)


def _answer_callback(callback_id, text=""):
    return _telegram("answerCallbackQuery", callback_query_id=callback_id, text=text)


def _authorized(actor_id):
    # Fail closed: a private household bot must never become public because an
    # allow-list variable was accidentally omitted.
    return bool(ALLOWED_USERS) and int(actor_id) in ALLOWED_USERS


def _show_home(chat_id):
    payload = STORE.load()
    count = len(payload["shopping"])
    stats = consumption_stats(payload)
    due = sum(1 for item_id, row in stats.items() if row["due"] and item_id not in payload["shopping"])
    _send(
        chat_id,
        "🏠 مدیریت خرید خانه\n\n"
        f"🛒 {count} قلم در لیست خرید\n"
        f"⚠️ {due} قلم احتمالاً رو به اتمام\n\n"
        "یک گزینه را انتخاب کنید:",
        _main_menu(),
    )


def _show_categories(chat_id):
    _send(chat_id, "دسته‌بندی کالا را انتخاب کنید:", _category_keyboard())


def _show_catalog(chat_id, category):
    category_info = CATEGORIES.get(category)
    if not category_info:
        _show_categories(chat_id)
        return
    payload = STORE.load()
    rows = []
    for item_id, item in CATALOG.items():
        if item["category"] != category:
            continue
        quantity = int((payload["shopping"].get(item_id) or {}).get("quantity") or 0)
        prefix = f"✅ {quantity}× " if quantity else "➕ "
        rows.append([{
            "text": prefix + item["name"],
            "callback_data": f"add:{item_id}",
        }])
    rows.append([{"text": "⬅️ دسته‌بندی‌ها", "callback_data": "categories"}])
    _send(chat_id, f"{category_info[0]}\nبرای افزودن روی کالا بزنید:", _inline(rows))


def _show_shopping(chat_id, purchasing=False):
    payload = STORE.load()
    shopping = payload["shopping"]
    if not shopping:
        _send(chat_id, "🛒 لیست خرید خالی است.", _category_keyboard())
        return
    lines = ["✅ کالاهای خریداری‌شده را انتخاب کنید:" if purchasing else "🛒 لیست خرید خانه:"]
    rows = []
    for item_id, row in shopping.items():
        item = CATALOG.get(item_id)
        if not item:
            continue
        quantity = int(row.get("quantity") or 1)
        lines.append(f"• {item['name']} — {quantity} عدد")
        if purchasing:
            rows.append([{
                "text": f"✅ {item['name']}",
                "callback_data": f"buy:{item_id}",
            }])
        else:
            rows.append([
                {"text": f"➕ {item['name']}", "callback_data": f"add:{item_id}"},
                {"text": "🗑", "callback_data": f"remove:{item_id}"},
            ])
    rows.append([{"text": "➕ افزودن کالا", "callback_data": "categories"}])
    rows.append([{"text": "⬅️ بازگشت", "callback_data": "home"}])
    _send(chat_id, "\n".join(lines), _inline(rows))


def _show_quantity(chat_id, item_id):
    item = CATALOG.get(item_id)
    if not item:
        _show_shopping(chat_id, purchasing=True)
        return
    rows = [[
        {"text": str(quantity), "callback_data": f"qty:{item_id}:{quantity}"}
        for quantity in (1, 2, 3, 4)
    ], [{"text": "⬅️ بازگشت", "callback_data": "purchase-list"}]]
    _send(chat_id, f"از «{item['name']}» چند عدد خریدید؟", _inline(rows))


def _show_due(chat_id):
    payload = STORE.load()
    stats = consumption_stats(payload)
    rows = []
    lines = ["⚠️ کالاهایی که براساس مصرف قبلی احتمالاً رو به اتمام‌اند:"]
    for item_id, row in sorted(stats.items(), key=lambda entry: entry[1]["next_date"] or date.max):
        if not row["due"] or item_id in payload["shopping"]:
            continue
        item = CATALOG[item_id]
        lines.append(f"• {item['name']} — چرخه تقریبی {row['average_days']} روز")
        rows.append([{
            "text": f"➕ {item['name']}",
            "callback_data": f"add:{item_id}",
        }])
    if not rows:
        _send(chat_id, "✅ فعلاً کالای رو به اتمام شناسایی نشده است.\nبا ثبت خریدها، پیش‌بینی دقیق‌تر می‌شود.", _main_menu())
        return
    rows.append([{"text": "⬅️ بازگشت", "callback_data": "home"}])
    _send(chat_id, "\n".join(lines), _inline(rows))


def _show_trends(chat_id):
    payload = STORE.load()
    stats = consumption_stats(payload)
    learned = [
        (item_id, row) for item_id, row in stats.items() if row["average_days"]
    ]
    learned.sort(key=lambda entry: entry[1]["average_days"])
    if not learned:
        _send(
            chat_id,
            "📊 برای محاسبه روند مصرف، حداقل دو خرید از یک کالا را ثبت کنید.",
            _main_menu(),
        )
        return
    lines = ["📊 روند مصرف خانه:"]
    for item_id, row in learned[:20]:
        next_text = row["next_date"].strftime("%Y-%m-%d") if row["next_date"] else "—"
        lines.append(
            f"• {CATALOG[item_id]['name']}: هر {row['average_days']} روز | خرید بعدی حدود {next_text}"
        )
    _send(chat_id, "\n".join(lines), _main_menu())


def _show_history(chat_id):
    rows = STORE.load()["purchases"][-20:]
    if not rows:
        _send(chat_id, "📜 هنوز خریدی ثبت نشده است.", _main_menu())
        return
    lines = ["📜 آخرین خریدها:"]
    for row in reversed(rows):
        purchased = _parse_day(row.get("purchased_at"))
        when = purchased.strftime("%Y-%m-%d") if purchased else "—"
        lines.append(f"• {row.get('name', 'کالا')} — {row.get('quantity', 1)} عدد — {when}")
    _send(chat_id, "\n".join(lines), _main_menu())


def handle_update(data):
    callback = data.get("callback_query") or {}
    message = data.get("message") or {}
    actor = (callback.get("from") or message.get("from") or {}).get("id")
    source_message = callback.get("message") or message
    chat_id = (source_message.get("chat") or {}).get("id")
    if not actor or not chat_id:
        return
    if not _authorized(actor):
        _send(chat_id, "⛔ این ربات خصوصی است.")
        return

    if callback:
        callback_id = callback.get("id")
        action = str(callback.get("data") or "")
        if action == "home":
            _answer_callback(callback_id)
            _show_home(chat_id)
        elif action == "categories":
            _answer_callback(callback_id)
            _show_categories(chat_id)
        elif action.startswith("category:"):
            _answer_callback(callback_id)
            _show_catalog(chat_id, action.split(":", 1)[1])
        elif action.startswith("add:"):
            item_id = action.split(":", 1)[1]
            if item_id in CATALOG:
                STORE.add_to_list(item_id)
                _answer_callback(callback_id, f"{CATALOG[item_id]['name']} اضافه شد")
                _show_catalog(chat_id, CATALOG[item_id]["category"])
        elif action.startswith("remove:"):
            _answer_callback(callback_id, "از لیست حذف شد")
            STORE.remove_from_list(action.split(":", 1)[1])
            _show_shopping(chat_id)
        elif action == "purchase-list":
            _answer_callback(callback_id)
            _show_shopping(chat_id, purchasing=True)
        elif action.startswith("buy:"):
            _answer_callback(callback_id)
            _show_quantity(chat_id, action.split(":", 1)[1])
        elif action.startswith("qty:"):
            _, item_id, quantity = action.split(":", 2)
            if item_id in CATALOG and quantity.isdigit():
                name = CATALOG[item_id]["name"]
                STORE.record_purchase(item_id, int(quantity))
                _answer_callback(callback_id, f"خرید {name} ثبت شد")
                _show_shopping(chat_id, purchasing=True)
        else:
            _answer_callback(callback_id)
        return

    text = str(message.get("text") or "").strip()
    if text in ("/start", "/menu", "🏠 منوی اصلی"):
        _show_home(chat_id)
    elif text == "🛒 لیست خرید":
        _show_shopping(chat_id)
    elif text == "➕ افزودن کالا":
        _show_categories(chat_id)
    elif text == "✅ ثبت خرید":
        _show_shopping(chat_id, purchasing=True)
    elif text == "⚠️ رو به اتمام":
        _show_due(chat_id)
    elif text == "📊 روند مصرف":
        _show_trends(chat_id)
    elif text == "📜 تاریخچه خرید":
        _show_history(chat_id)
    else:
        _send(chat_id, "لطفاً یکی از دکمه‌ها را انتخاب کنید.", _main_menu())


def _configure_telegram():
    if not BOT_TOKEN or not PUBLIC_URL:
        return {"ok": False, "description": "token_or_public_url_missing"}
    webhook = {
        "url": f"{PUBLIC_URL}/webhook/household",
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    if WEBHOOK_SECRET:
        webhook["secret_token"] = WEBHOOK_SECRET
    webhook_result = _telegram("setWebhook", **webhook)
    commands_result = _telegram(
        "setMyCommands",
        commands=[
            {"command": "start", "description": "باز کردن مدیریت خانه"},
            {"command": "menu", "description": "نمایش منوی اصلی"},
        ],
    )
    logger.info("HOUSEHOLD BOT SETUP webhook=%s commands=%s", webhook_result.get("ok"), commands_result.get("ok"))
    return {"ok": bool(webhook_result.get("ok") and commands_result.get("ok")), "webhook": webhook_result, "commands": commands_result}


def init_household_bot(app):
    """Register routes once; safely do nothing when the token is absent."""
    if app.config.get("HOUSEHOLD_BOT_REGISTERED") or not BOT_TOKEN:
        if not BOT_TOKEN:
            logger.info("HOUSEHOLD BOT inactive: HOUSEHOLD_BOT_TOKEN not configured")
        return False
    app.config["HOUSEHOLD_BOT_REGISTERED"] = True

    @app.post("/webhook/household")
    def household_webhook():
        if WEBHOOK_SECRET:
            supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
                return "forbidden", 403
        data = request.get_json(force=True, silent=True)
        if data:
            threading.Thread(target=handle_update, args=(data,), daemon=True).start()
        return "ok", 200

    @app.get("/setup/household")
    def household_setup():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key", ""), SETUP_SECRET):
            return "forbidden", 403
        return jsonify(_configure_telegram())

    @app.get("/status/household")
    def household_status():
        if not SETUP_SECRET or not hmac.compare_digest(request.args.get("key", ""), SETUP_SECRET):
            return "forbidden", 403
        payload = STORE.load()
        return jsonify({
            "status": "ok",
            "shopping_items": len(payload["shopping"]),
            "purchase_records": len(payload["purchases"]),
        })

    # A fresh token or URL activates itself on the next Railway deployment.
    threading.Thread(target=_configure_telegram, daemon=True).start()
    logger.info("HOUSEHOLD BOT routes registered")
    return True
